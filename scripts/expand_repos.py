#!/usr/bin/env python3
"""
Expand repos from data_classify.csv:

1. For each row with entity_type=organization, list all repos under that org
   via the GitHub API (stars, forks, pushed_at).
2. Score each repo with:

       score = 2 * log10(stars + 1)
             + 1 * log10(forks + 1)
             + 3 * exp(-days_since_last_push / 180)

   (stars/forks reflect popularity on a log scale; the recency term is a
   half-life-style decay that rewards repos still being pushed to.)
3. Keep the top 20 repos per org by score.
4. Merge with all entity_type=repo rows from data_classify.csv.
5. Deduplicate by normalized URL; original repo rows always win.

Input:  output/data_classify.csv
Output: output/repos.csv
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CACHE_DIR = Path("output/.cache")
CACHE_FILE = CACHE_DIR / "org_repos_expansion_cache.json"

_rate_remaining = None
_rate_reset = None


def _interruptible_wait(seconds, label="Rate limit reset"):
    end = time.time() + seconds
    while True:
        remaining = int(end - time.time())
        if remaining <= 0:
            break
        print(f"\r  ⏳ {label}: {remaining}s  ", end="", file=sys.stderr, flush=True)
        time.sleep(min(5, remaining))
    print(f"\r  ✓ {label} done.{' ' * 40}", file=sys.stderr)


def _load_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    tmp.replace(CACHE_FILE)


def github_api(endpoint):
    global _rate_remaining, _rate_reset
    url = f"https://api.github.com{endpoint}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oss-x-expand-repos",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    if _rate_remaining is not None and _rate_remaining <= 1 and _rate_reset:
        wait = _rate_reset - int(time.time()) + 1
        if wait > 0:
            _interruptible_wait(wait)

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
                if wait > 0:
                    _interruptible_wait(wait, "403 retry")
                    return github_api(endpoint)
        elif e.code in (404, 422):
            return None
        print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  Network error: {e.reason}", file=sys.stderr)
        return None


def fetch_org_repos(owner):
    """List all non-fork, non-archived repos under an org/user."""
    # Try /orgs first; fall back to /users for personal accounts.
    for kind in ("orgs", "users"):
        repos = []
        page = 1
        ok = False
        while True:
            data = github_api(
                f"/{kind}/{owner}/repos?per_page=100&page={page}&type=public&sort=updated"
            )
            if data is None:
                break
            ok = True
            if not isinstance(data, list) or not data:
                break
            for r in data:
                if r.get("fork") or r.get("archived"):
                    continue
                repos.append({
                    "name": r.get("name", ""),
                    "full_name": r.get("full_name", ""),
                    "url": r.get("html_url", ""),
                    "stars": r.get("stargazers_count", 0),
                    "forks": r.get("forks_count", 0),
                    "pushed_at": r.get("pushed_at", "") or "",
                    "description": (r.get("description") or "")[:200],
                    "language": r.get("language") or "",
                })
            if len(data) < 100:
                break
            page += 1
        if ok:
            return repos
    return []


def score_repo(repo, now=None):
    now = now or datetime.now(timezone.utc)
    stars = repo.get("stars", 0) or 0
    forks = repo.get("forks", 0) or 0
    pushed = repo.get("pushed_at") or ""
    try:
        dt = datetime.strptime(pushed, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        days = max(0, (now - dt).days)
    except ValueError:
        days = 10_000
    s = math.log10(stars + 1)
    f = math.log10(forks + 1)
    r = math.exp(-days / 180.0)
    return round(2 * s + 1 * f + 3 * r, 4)


URL_KEY_RE = re.compile(r"^https?://")


def url_key(url):
    u = (url or "").strip().rstrip("/").lower()
    if u.endswith(".git"):
        u = u[:-4]
    return URL_KEY_RE.sub("", u)


def extract_github_owner(url):
    parsed = urlparse((url or "").strip().rstrip("/"))
    if (parsed.hostname or "").lower() == "github.com":
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts:
            return parts[0]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", default="output/data_classify.csv")
    ap.add_argument("-o", "--output", default="output/repos.csv")
    ap.add_argument("--top", type=int, default=20, help="Top N repos per org")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    original_repo_rows = [r for r in rows if (r.get("entity_type") or "").strip() == "repo"]
    org_rows = [r for r in rows if (r.get("entity_type") or "").strip() == "organization"]

    print(f"Original repos: {len(original_repo_rows)}", file=sys.stderr)
    print(f"Organizations:  {len(org_rows)}", file=sys.stderr)

    cache = {} if args.no_cache else _load_cache()

    expanded = []
    github_org_count = 0
    for i, org in enumerate(org_rows, 1):
        url = org.get("上游地址", "")
        owner = extract_github_owner(url)
        if not owner:
            print(f"  [{i}/{len(org_rows)}] skip non-GitHub: {url}", file=sys.stderr)
            continue
        github_org_count += 1
        key = owner.lower()
        if key in cache:
            repos = cache[key]
            print(f"  [{i}/{len(org_rows)}] {owner}: {len(repos)} repos (cached)", file=sys.stderr)
        else:
            repos = fetch_org_repos(owner)
            cache[key] = repos
            _save_cache(cache)
            rl = f" [remaining={_rate_remaining}]" if _rate_remaining is not None else ""
            print(f"  [{i}/{len(org_rows)}] {owner}: {len(repos)} repos{rl}", file=sys.stderr)

        for r in repos:
            r["_score"] = score_repo(r)
        repos_sorted = sorted(repos, key=lambda x: x["_score"], reverse=True)[: args.top]
        for r in repos_sorted:
            expanded.append({
                "项目名称": r["name"],
                "上游地址": r["url"],
                "entity_type": "repo",
                "source": "org_expansion",
                "expanded_from_org": owner,
                "stars": r["stars"],
                "forks": r["forks"],
                "pushed_at": r["pushed_at"],
                "score": r["_score"],
                "language": r["language"],
                "description": r["description"],
            })

    # Merge — original rows win on URL collision.
    seen = set()
    output_fields = [
        "页签", "序号", "项目名称", "分类", "上游地址", "entity_type",
        "source", "expanded_from_org", "stars", "forks", "pushed_at",
        "score", "language", "description", "reason",
    ]
    out_rows = []

    for r in original_repo_rows:
        k = url_key(r.get("上游地址", ""))
        if not k or k in seen:
            continue
        seen.add(k)
        out_rows.append({
            "页签": r.get("页签", ""),
            "序号": r.get("序号", ""),
            "项目名称": r.get("项目名称", ""),
            "分类": r.get("分类", ""),
            "上游地址": r.get("上游地址", ""),
            "entity_type": "repo",
            "source": "repo",
            "expanded_from_org": "",
            "stars": "", "forks": "", "pushed_at": "",
            "score": "", "language": "", "description": "",
            "reason": r.get("reason", ""),
        })

    dedup_expanded = 0
    for r in expanded:
        k = url_key(r["上游地址"])
        if not k or k in seen:
            dedup_expanded += 1
            continue
        seen.add(k)
        out_rows.append({
            "页签": "", "序号": "", "项目名称": r["项目名称"],
            "分类": "", "上游地址": r["上游地址"],
            "entity_type": "repo", "source": "org_expansion",
            "expanded_from_org": r["expanded_from_org"],
            "stars": r["stars"], "forks": r["forks"], "pushed_at": r["pushed_at"],
            "score": r["score"], "language": r["language"],
            "description": r["description"],
            "reason": f"org_expansion: {r['expanded_from_org']} (score={r['score']})",
        })

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=output_fields)
        w.writeheader()
        for row in out_rows:
            w.writerow({k: row.get(k, "") for k in output_fields})

    if args.summary:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Repo Expansion Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Original repos:      {len(original_repo_rows)}", file=sys.stderr)
        print(f"  GitHub orgs processed: {github_org_count}/{len(org_rows)}", file=sys.stderr)
        print(f"  Expansion candidates: {len(expanded)}", file=sys.stderr)
        print(f"  Dedup dropped:       {dedup_expanded}", file=sys.stderr)
        print(f"  Final rows in {args.output}: {len(out_rows)}", file=sys.stderr)
        print(f"  Top-N per org:       {args.top}", file=sys.stderr)


if __name__ == "__main__":
    main()
