#!/usr/bin/env python3
"""
Expand organizations from data_classify.csv.

For every row where entity_type == "repo", determine the parent organization:
  1. URL-based: parse the upstream URL (github.com / gitee.com / gitlab.*) and,
     for GitHub, verify via /users/{owner} that the owner is an Organization.
  2. Unresolved rows (no parseable URL, or URL points to a personal user account)
     are flagged source=pending_llm so the skill layer can resolve them via
     Web Search + LLM inference (with s/a/b/c confidence).

Output: output/organizations.csv aggregated per organization.

Usage:
  python3 scripts/expand_orgs.py output/data_classify.csv -o output/organizations.csv --summary
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CACHE_DIR = Path("output/.cache")
CACHE_FILE = CACHE_DIR / "github_owners_cache.json"

NON_GITHUB_GIT_HOSTS = {
    "gitlab.com", "gitlab.freedesktop.org", "gitlab.gnome.org",
    "salsa.debian.org", "gitee.com", "codeberg.org",
    "code.videolan.org", "git.kernel.org",
}
GITLAB_PATTERN = re.compile(r"^gitlab\.", re.IGNORECASE)

_rate_remaining = None
_rate_reset = None


def _wait(seconds: int, label: str = "Rate limit reset") -> None:
    end = time.time() + seconds
    while True:
        remaining = int(end - time.time())
        if remaining <= 0:
            break
        print(f"\r  ⏳ {label}: {remaining}s  ", end="", file=sys.stderr, flush=True)
        time.sleep(min(5, remaining))
    print(f"\r  ✓ {label} complete.{' ' * 30}", file=sys.stderr)


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def github_api(endpoint: str) -> dict | list | None:
    global _rate_remaining, _rate_reset
    url = f"https://api.github.com{endpoint}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "oss-x-expand-orgs"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    if _rate_remaining is not None and _rate_remaining <= 1 and _rate_reset:
        wait = _rate_reset - int(time.time()) + 1
        if wait > 0:
            _wait(wait)

    try:
        with urlopen(Request(url, headers=headers), timeout=30) as resp:
            _rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
            _rate_reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            return json.loads(resp.read().decode())
    except HTTPError as e:
        if e.code == 403:
            reset = e.headers.get("X-RateLimit-Reset")
            if reset:
                wait = int(reset) - int(time.time()) + 1
                if wait > 0:
                    _wait(wait, "403 retry")
                    return github_api(endpoint)
        elif e.code == 404:
            return None
        print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  Network error: {e.reason}", file=sys.stderr)
        return None


def parse_url(url: str) -> tuple[str | None, str | None]:
    """Return (platform, owner) for a repo URL, or (None, None) if unparseable."""
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        return None, None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        return None, None
    if host == "github.com":
        return "github.com", parts[0]
    if host in NON_GITHUB_GIT_HOSTS or GITLAB_PATTERN.match(host):
        return host, parts[0]
    return None, None


def resolve_github_owner(owner: str) -> dict:
    data = github_api(f"/users/{owner}")
    if data and isinstance(data, dict):
        is_org = data.get("type") == "Organization"
        return {
            "owner_type": "organization" if is_org else "user",
            "name": data.get("name") or owner,
            "description": data.get("bio") or data.get("description") or "",
            "blog": data.get("blog") or "",
            "location": data.get("location") or "",
        }
    return {"owner_type": "unknown", "name": owner, "description": "", "blog": "", "location": ""}


def main():
    parser = argparse.ArgumentParser(description="Expand organizations from data_classify.csv")
    parser.add_argument("csv_file", help="Path to data_classify.csv")
    parser.add_argument("-o", "--output", default="output/organizations.csv")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    with open(args.csv_file, "r", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("entity_type", "").strip() == "repo"]

    print(f"Loaded {len(rows)} repo rows from {args.csv_file}", file=sys.stderr)

    # Group by (platform, owner) for URL-resolvable; collect pending for LLM fallback
    # key: (platform, owner_lower); value: {owner, platform, repos:[rows]}
    owner_map: dict[tuple[str, str], dict] = {}
    pending_rows: list[dict] = []

    for row in rows:
        url = row.get("上游地址", "").strip()
        platform, owner = parse_url(url)
        if platform and owner:
            key = (platform, owner.lower())
            owner_map.setdefault(key, {"owner": owner, "platform": platform, "repos": []})
            owner_map[key]["repos"].append(row)
        else:
            pending_rows.append(row)

    print(f"URL-resolvable owners: {len(owner_map)} | Pending LLM: {len(pending_rows)}",
          file=sys.stderr)

    # Resolve GitHub owners via API to confirm Organization vs User
    cache = {} if args.no_cache else _load_cache()
    resolved: dict[tuple[str, str], dict] = {}

    gh_keys = [k for k in owner_map if k[0] == "github.com"]
    to_query = [k for k in gh_keys if k[1] not in cache]
    print(f"GitHub owners: {len(gh_keys)} total, "
          f"{len(gh_keys) - len(to_query)} cached, {len(to_query)} to query", file=sys.stderr)

    for i, key in enumerate(to_query, 1):
        owner = owner_map[key]["owner"]
        if i % 10 == 0 or i == len(to_query):
            print(f"  [{i}/{len(to_query)}] resolving {owner}", file=sys.stderr)
        try:
            info = resolve_github_owner(owner)
        except KeyboardInterrupt:
            _save_cache(cache)
            sys.exit(130)
        cache[key[1]] = info
        if i % 20 == 0:
            _save_cache(cache)
    _save_cache(cache)

    for key in gh_keys:
        resolved[key] = cache.get(key[1], {"owner_type": "unknown", "name": owner_map[key]["owner"],
                                           "description": "", "blog": "", "location": ""})

    # Build output rows
    fieldnames = [
        "org_name", "owner", "platform", "org_url",
        "repo_count", "unique_repo_count", "repos",
        "source", "confidence", "reason",
        "description", "blog", "location",
    ]
    out_rows: list[dict] = []
    user_account_repos: list[dict] = []  # personal accounts → LLM fallback

    for key, info in owner_map.items():
        platform, _ = key
        owner = info["owner"]
        repos = info["repos"]
        repo_names = ";".join(r.get("项目名称", "") for r in repos)
        unique_repo_count = len({r.get("上游地址", "").strip() for r in repos if r.get("上游地址", "").strip()})

        if platform == "github.com":
            r = resolved[key]
            # Personal user accounts are not real orgs → push to LLM fallback
            if r["owner_type"] != "organization":
                for row in repos:
                    user_account_repos.append(row)
                continue
            out_rows.append({
                "org_name": r["name"],
                "owner": owner,
                "platform": "github.com",
                "org_url": f"https://github.com/{owner}",
                "repo_count": len(repos),
                "unique_repo_count": unique_repo_count,
                "repos": repo_names,
                "source": "url+github_api",
                "confidence": "",
                "reason": f"Resolved from URL host github.com/{owner}; GitHub API type=Organization",
                "description": r["description"],
                "blog": r["blog"],
                "location": r["location"],
            })
        else:
            out_rows.append({
                "org_name": owner,
                "owner": owner,
                "platform": platform,
                "org_url": f"https://{platform}/{owner}",
                "repo_count": len(repos),
                "unique_repo_count": unique_repo_count,
                "repos": repo_names,
                "source": "url",
                "confidence": "",
                "reason": f"Resolved from URL host {platform}/{owner}",
                "description": "", "blog": "", "location": "",
            })

    # Pending rows (unparseable URL + personal GitHub users) → one placeholder row each
    for row in pending_rows + user_account_repos:
        proj = row.get("项目名称", "")
        url = row.get("上游地址", "")
        reason_src = "unparseable URL" if row in pending_rows else "GitHub owner is a personal user account, not an organization"
        out_rows.append({
            "org_name": "",
            "owner": "",
            "platform": "",
            "org_url": "",
            "repo_count": 1,
            "unique_repo_count": 1 if url.strip() else 0,
            "repos": proj,
            "source": "pending_llm",
            "confidence": "",
            "reason": f"{reason_src}; upstream={url}. Fill org_name/org_url/confidence(s/a/b/c)/reason via Web Search.",
            "description": "", "blog": "", "location": "",
        })

    # Sort: resolved orgs by repo_count desc, pending last
    out_rows.sort(key=lambda r: (r["source"] == "pending_llm", -int(r["repo_count"])))

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    resolved_n = sum(1 for r in out_rows if r["source"] != "pending_llm")
    pending_n = len(out_rows) - resolved_n
    print(f"Wrote {args.output}: {resolved_n} resolved orgs + {pending_n} pending", file=sys.stderr)

    if args.summary:
        print(f"\n{'='*60}", file=sys.stderr)
        print("Org Expansion Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  repo rows in input:  {len(rows)}", file=sys.stderr)
        print(f"  URL-resolved orgs:   {resolved_n}", file=sys.stderr)
        print(f"  Pending LLM lookup:  {pending_n}", file=sys.stderr)

    sys.exit(1 if pending_n else 0)


if __name__ == "__main__":
    main()
