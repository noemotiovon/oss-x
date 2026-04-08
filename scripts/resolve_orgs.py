#!/usr/bin/env python3
"""
Resolve organizations from repo.csv by extracting GitHub owners and querying the API.

For each repo URL, extracts the GitHub owner, deduplicates, queries the GitHub API
to determine if the owner is an organization or user, collects metadata, and outputs
organization.csv with deduplicated organization entries.

Non-GitHub URLs are flagged for manual review.

Requirements:
  - GITHUB_TOKEN env var (optional but recommended to avoid rate limits)
  - Python 3.10+

Usage:
  python3 scripts/resolve_orgs.py output/repo.csv -o output/organization.csv --summary
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Rate limit tracking
_rate_remaining = None
_rate_reset = None


def github_api(endpoint: str) -> dict | list | None:
    """Make a GitHub API request. Returns parsed JSON or None on error."""
    global _rate_remaining, _rate_reset

    url = f"https://api.github.com{endpoint}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oss-x-resolve-orgs",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    # Proactive rate limit wait
    if _rate_remaining is not None and _rate_remaining <= 1 and _rate_reset:
        wait = _rate_reset - int(time.time()) + 1
        if wait > 0:
            print(f"  Rate limit nearly exhausted, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            _rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
            _rate_reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            return json.loads(resp.read().decode())
    except HTTPError as e:
        if e.code == 403:
            reset = e.headers.get("X-RateLimit-Reset")
            if reset:
                wait = int(reset) - int(time.time()) + 1
                print(f"  Rate limited. Reset in {wait}s", file=sys.stderr)
            else:
                print(f"  403 Forbidden: {url}", file=sys.stderr)
        elif e.code == 404:
            return None  # Not found — expected for users when querying /orgs/
        else:
            print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  Network error: {e.reason}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# URL parsing helpers
# ---------------------------------------------------------------------------

# Known git hosting platforms (non-GitHub)
NON_GITHUB_GIT_HOSTS = {
    "gitlab.com",
    "gitlab.freedesktop.org",
    "gitlab.gnome.org",
    "salsa.debian.org",
    "gitee.com",
    "codeberg.org",
    "code.videolan.org",
    "git.kernel.org",
    "git.musl-libc.org",
    "git.whamcloud.com",
}

GITLAB_PATTERN = re.compile(r"^gitlab\.", re.IGNORECASE)


def parse_github_owner(url: str) -> str | None:
    """Extract GitHub owner from a repo URL like https://github.com/owner/repo."""
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != "github.com":
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 1:
        return parts[0]
    return None


def parse_non_github_host(url: str) -> str | None:
    """Return the hostname if URL is from a known non-GitHub git host."""
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in NON_GITHUB_GIT_HOSTS or GITLAB_PATTERN.match(host):
        return host
    return None


def extract_owner_from_non_github(url: str) -> str | None:
    """Extract owner/org from non-GitHub git hosting URLs."""
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    host = (parsed.hostname or "").lower()

    # gitee.com/owner/repo -> owner
    if host == "gitee.com" and len(parts) >= 1:
        return parts[0]
    # gitlab.*/owner/repo -> owner
    if ("gitlab" in host or host in NON_GITHUB_GIT_HOSTS) and len(parts) >= 1:
        return parts[0]
    return None


# ---------------------------------------------------------------------------
# GitHub owner type resolution
# ---------------------------------------------------------------------------

def resolve_github_owner(owner: str) -> dict:
    """
    Query GitHub API to determine if owner is an org or user.
    Returns dict with type and metadata.
    """
    # Try as organization first
    org_data = github_api(f"/orgs/{owner}")
    if org_data and isinstance(org_data, dict):
        return {
            "owner": owner,
            "owner_type": "organization",
            "name": org_data.get("name") or owner,
            "description": org_data.get("description") or "",
            "blog": org_data.get("blog") or "",
            "location": org_data.get("location") or "",
            "public_repos": org_data.get("public_repos", 0),
            "url": f"https://github.com/{owner}",
            "source": "github_api",
        }

    # Try as user
    user_data = github_api(f"/users/{owner}")
    if user_data and isinstance(user_data, dict):
        user_type = user_data.get("type", "User")
        # Some orgs respond to /users/ but not /orgs/
        if user_type == "Organization":
            return {
                "owner": owner,
                "owner_type": "organization",
                "name": user_data.get("name") or owner,
                "description": user_data.get("bio") or "",
                "blog": user_data.get("blog") or "",
                "location": user_data.get("location") or "",
                "public_repos": user_data.get("public_repos", 0),
                "url": f"https://github.com/{owner}",
                "source": "github_api",
            }
        else:
            return {
                "owner": owner,
                "owner_type": "user",
                "name": user_data.get("name") or owner,
                "description": user_data.get("bio") or "",
                "blog": user_data.get("blog") or "",
                "location": user_data.get("location") or "",
                "public_repos": user_data.get("public_repos", 0),
                "url": f"https://github.com/{owner}",
                "source": "github_api",
            }

    # API failed for both
    return {
        "owner": owner,
        "owner_type": "unknown",
        "name": owner,
        "description": "",
        "blog": "",
        "location": "",
        "public_repos": 0,
        "url": f"https://github.com/{owner}",
        "source": "api_error",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Resolve organizations from repo.csv"
    )
    parser.add_argument("csv_file", help="Path to repo.csv")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # --- Read repo.csv ---
    rows = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # --- Extract owners from all repo URLs ---
    # owner_key -> { "owner": str, "repos": [row, ...], "页签s": set, "分类s": set, "platform": str }
    owner_map = {}
    non_github_repos = []
    unparseable_repos = []

    for row in rows:
        url = row.get("上游地址", "").strip()
        if not url or not url.startswith("http"):
            unparseable_repos.append(row)
            continue

        github_owner = parse_github_owner(url)
        if github_owner:
            key = github_owner.lower()
            if key not in owner_map:
                owner_map[key] = {
                    "owner": github_owner,
                    "repos": [],
                    "页签s": set(),
                    "分类s": set(),
                    "platform": "github.com",
                }
            owner_map[key]["repos"].append(row)
            owner_map[key]["页签s"].add(row.get("页签", ""))
            owner_map[key]["分类s"].add(row.get("分类", ""))
            continue

        non_github_host = parse_non_github_host(url)
        if non_github_host:
            non_github_owner = extract_owner_from_non_github(url)
            if non_github_owner:
                key = f"{non_github_host}/{non_github_owner}".lower()
                if key not in owner_map:
                    owner_map[key] = {
                        "owner": non_github_owner,
                        "repos": [],
                        "页签s": set(),
                        "分类s": set(),
                        "platform": non_github_host,
                    }
                owner_map[key]["repos"].append(row)
                owner_map[key]["页签s"].add(row.get("页签", ""))
                owner_map[key]["分类s"].add(row.get("分类", ""))
            else:
                non_github_repos.append(row)
            continue

        unparseable_repos.append(row)

    print(f"Found {len(owner_map)} unique owners from {len(rows)} repos", file=sys.stderr)
    print(f"  Non-GitHub repos (parseable host): {len(non_github_repos)}", file=sys.stderr)
    print(f"  Unparseable URLs: {len(unparseable_repos)}", file=sys.stderr)

    # --- Resolve GitHub owners via API ---
    github_owners = {k: v for k, v in owner_map.items() if v["platform"] == "github.com"}
    non_github_owners = {k: v for k, v in owner_map.items() if v["platform"] != "github.com"}

    print(f"\nResolving {len(github_owners)} GitHub owners via API...", file=sys.stderr)
    resolved = {}
    for i, (key, info) in enumerate(github_owners.items(), 1):
        owner = info["owner"]
        if i % 50 == 0 or i == len(github_owners):
            print(f"  Progress: {i}/{len(github_owners)}", file=sys.stderr)
        result = resolve_github_owner(owner)
        resolved[key] = result

    # --- Build output rows ---
    output_fieldnames = [
        "owner",          # GitHub owner / org login
        "owner_type",     # organization, user, non_github, manual_review
        "name",           # Display name
        "platform",       # github.com, gitee.com, etc.
        "url",            # Org URL
        "repo_count",     # Number of repos in repo.csv under this owner
        "页签",           # Comma-joined 页签 values
        "分类",           # Comma-joined 分类 values
        "description",    # Org description
        "blog",           # Org website
        "location",       # Org location
        "public_repos",   # Total public repos (from API)
        "source",         # How it was resolved
        "repos_list",     # Semicolon-joined repo names
    ]

    output_rows = []

    # GitHub owners
    for key, info in github_owners.items():
        r = resolved.get(key, {})
        repo_names = [row.get("项目名称", "") for row in info["repos"]]
        output_rows.append({
            "owner": info["owner"],
            "owner_type": r.get("owner_type", "unknown"),
            "name": r.get("name", info["owner"]),
            "platform": "github.com",
            "url": f"https://github.com/{info['owner']}",
            "repo_count": len(info["repos"]),
            "页签": ",".join(sorted(info["页签s"] - {""})),
            "分类": ",".join(sorted(info["分类s"] - {""})),
            "description": r.get("description", ""),
            "blog": r.get("blog", ""),
            "location": r.get("location", ""),
            "public_repos": r.get("public_repos", 0),
            "source": r.get("source", ""),
            "repos_list": ";".join(repo_names),
        })

    # Non-GitHub owners (from known git hosts)
    for key, info in non_github_owners.items():
        repo_names = [row.get("项目名称", "") for row in info["repos"]]
        output_rows.append({
            "owner": info["owner"],
            "owner_type": "non_github",
            "name": info["owner"],
            "platform": info["platform"],
            "url": f"https://{info['platform']}/{info['owner']}",
            "repo_count": len(info["repos"]),
            "页签": ",".join(sorted(info["页签s"] - {""})),
            "分类": ",".join(sorted(info["分类s"] - {""})),
            "description": "",
            "blog": "",
            "location": "",
            "public_repos": 0,
            "source": "non_github_host",
            "repos_list": ";".join(repo_names),
        })

    # Unparseable / non-github repos without owner
    for row in non_github_repos + unparseable_repos:
        url = row.get("上游地址", "")
        output_rows.append({
            "owner": "",
            "owner_type": "manual_review",
            "name": row.get("项目名称", ""),
            "platform": "",
            "url": url,
            "repo_count": 1,
            "页签": row.get("页签", ""),
            "分类": row.get("分类", ""),
            "description": "",
            "blog": "",
            "location": "",
            "public_repos": 0,
            "source": "unparseable_url",
            "repos_list": row.get("项目名称", ""),
        })

    # Sort: organizations first, then by repo_count desc
    type_order = {"organization": 0, "user": 1, "non_github": 2, "unknown": 3, "manual_review": 4}
    output_rows.sort(key=lambda r: (type_order.get(r["owner_type"], 9), -r["repo_count"]))

    # --- Output ---
    if args.json:
        print(json.dumps(output_rows, ensure_ascii=False, indent=2))
    else:
        out = sys.stdout
        if args.output:
            out = open(args.output, "w", encoding="utf-8", newline="")

        writer = csv.DictWriter(out, fieldnames=output_fieldnames)
        writer.writeheader()
        for row in output_rows:
            writer.writerow(row)

        if args.output:
            out.close()

    # --- Summary ---
    if args.summary:
        org_count = sum(1 for r in output_rows if r["owner_type"] == "organization")
        user_count = sum(1 for r in output_rows if r["owner_type"] == "user")
        non_gh_count = sum(1 for r in output_rows if r["owner_type"] == "non_github")
        unknown_count = sum(1 for r in output_rows if r["owner_type"] == "unknown")
        manual_count = sum(1 for r in output_rows if r["owner_type"] == "manual_review")

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Organization Resolution Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Total repos in input:       {len(rows)}", file=sys.stderr)
        print(f"  Unique owners resolved:     {len(output_rows)}", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)
        print(f"  Organizations (GitHub):     {org_count}", file=sys.stderr)
        print(f"  Users (GitHub):             {user_count}", file=sys.stderr)
        print(f"  Non-GitHub owners:          {non_gh_count}", file=sys.stderr)
        print(f"  Unknown (API error):        {unknown_count}", file=sys.stderr)
        print(f"  Manual review needed:       {manual_count}", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)

        if manual_count > 0:
            print(f"\n  Items needing manual review:", file=sys.stderr)
            for r in output_rows:
                if r["owner_type"] == "manual_review":
                    print(f"    - {r['name']}: {r['url']}", file=sys.stderr)

        if unknown_count > 0:
            print(f"\n  Items with API errors:", file=sys.stderr)
            for r in output_rows:
                if r["owner_type"] == "unknown":
                    print(f"    - {r['owner']}: {r['url']}", file=sys.stderr)

    # Exit with code 1 if there are items needing manual review
    has_manual = any(r["owner_type"] in ("manual_review", "non_github") for r in output_rows)
    sys.exit(1 if has_manual else 0)


if __name__ == "__main__":
    main()
