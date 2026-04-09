#!/usr/bin/env python3
"""
Expand repos: discover additional popular repos from original organizations.

1. Copies all repo.csv entries with source=repo
2. For each org in organization.csv (GitHub orgs):
   - Fetches repos with stars > 100 AND active in last year
   - Adds them with source=org_expansion
3. Deduplicates (original repo.csv takes priority)
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
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
    end_time = time.time() + seconds
    while True:
        remaining = int(end_time - time.time())
        if remaining <= 0:
            break
        print(f"\r  ⏳ {label}: {remaining}s remaining  ", end="", file=sys.stderr, flush=True)
        time.sleep(min(5, remaining))
    print(f"\r  ✓ {label} complete.{' ' * 40}", file=sys.stderr)


def _load_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"  Loaded {len(data)} cached org repo lists", file=sys.stderr)
            return data
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
                    _interruptible_wait(wait, "403 rate-limit retry")
                    return github_api(endpoint)
        elif e.code in (404, 422):
            return None
        print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  Network error: {e.reason}", file=sys.stderr)
        return None


def fetch_org_active_starred_repos(org_login, min_stars=100):
    """Fetch repos from an org with stars > min_stars AND pushed in last year."""
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    repos = []
    page = 1
    while True:
        data = github_api(
            f"/search/repositories?q=org:{org_login}+stars:>{min_stars}+pushed:>{one_year_ago}"
            f"&sort=stars&order=desc&per_page=100&page={page}"
        )
        if not data or not isinstance(data, dict):
            break
        items = data.get("items", [])
        if not items:
            break
        for repo in items:
            repos.append({
                "name": repo.get("name", ""),
                "full_name": repo.get("full_name", ""),
                "url": repo.get("html_url", ""),
                "stars": repo.get("stargazers_count", 0),
                "pushed_at": repo.get("pushed_at", ""),
                "description": (repo.get("description") or "")[:200],
                "language": repo.get("language") or "",
            })
        if len(items) < 100:
            break
        page += 1
    return repos


def extract_repo_url_key(url):
    """Normalize a repo URL for deduplication."""
    url = (url or "").strip().rstrip("/").lower()
    if url.endswith(".git"):
        url = url[:-4]
    url = re.sub(r'^https?://', '', url)
    return url


def extract_github_owner(url):
    parsed = urlparse((url or "").strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    if host == "github.com":
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts:
            return parts[0]
    return None


def main():
    parser = argparse.ArgumentParser(description="Expand repos from original organizations")
    parser.add_argument("repo_csv", help="Path to repo.csv")
    parser.add_argument("org_csv", help="Path to organization.csv")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--min-stars", type=int, default=100, help="Minimum stars for expansion")
    args = parser.parse_args()

    # --- Read original repos ---
    original_repos = []
    with open(args.repo_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            original_repos.append(row)

    # Build dedup set from original repos
    existing_urls = set()
    for row in original_repos:
        url = row.get("上游地址", "")
        key = extract_repo_url_key(url)
        if key:
            existing_urls.add(key)

    print(f"Original repos: {len(original_repos)}", file=sys.stderr)
    print(f"Unique URLs: {len(existing_urls)}", file=sys.stderr)

    # --- Read organizations (from organization.csv, NOT org_exp_val.csv) ---
    orgs = []
    with open(args.org_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            orgs.append(row)

    # Filter to GitHub orgs only
    github_orgs = []
    non_github_orgs = []
    for org in orgs:
        url = org.get("上游地址", "").strip()
        owner = extract_github_owner(url)
        if owner:
            github_orgs.append((org, owner))
        else:
            non_github_orgs.append(org)

    print(f"\nOrganizations from organization.csv: {len(orgs)}", file=sys.stderr)
    print(f"  GitHub orgs to expand: {len(github_orgs)}", file=sys.stderr)
    print(f"  Non-GitHub orgs (skip API, mark for LLM): {len(non_github_orgs)}", file=sys.stderr)

    # --- Expand from GitHub orgs ---
    cache = {} if args.no_cache else _load_cache()
    expanded_repos = []

    for i, (org, owner) in enumerate(github_orgs, 1):
        key = owner.lower()
        org_name = org.get("项目名称", owner)

        if key in cache:
            repos = cache[key]
            print(f"  [{i}/{len(github_orgs)}] {owner}: {len(repos)} repos (cached)", file=sys.stderr)
        else:
            repos = fetch_org_active_starred_repos(owner, args.min_stars)
            cache[key] = repos
            _save_cache(cache)
            rl_info = f" [rate_remaining={_rate_remaining}]" if _rate_remaining is not None else ""
            print(f"  [{i}/{len(github_orgs)}] {owner}: {len(repos)} repos{rl_info}", file=sys.stderr)

        for repo in repos:
            url_key = extract_repo_url_key(repo["url"])
            if url_key and url_key not in existing_urls:
                existing_urls.add(url_key)
                expanded_repos.append({
                    "repo_name": repo["name"],
                    "repo_url": repo["url"],
                    "stars": repo["stars"],
                    "description": repo["description"],
                    "language": repo["language"],
                    "expanded_from_org": owner,
                    "org_name": org_name,
                })

    # --- Write output ---
    output_fields = [
        "页签", "序号", "项目名称", "分类", "上游地址", "entity_type", "reason",
        "source", "expanded_from_org", "stars", "description", "language", "llm_note",
    ]

    output_rows = []
    # Original repos
    for row in original_repos:
        out = {k: row.get(k, "") for k in output_fields}
        out["source"] = "repo"
        output_rows.append(out)

    # Expanded repos
    for repo in expanded_repos:
        output_rows.append({
            "页签": "",
            "序号": "",
            "项目名称": repo["repo_name"],
            "分类": "",
            "上游地址": repo["repo_url"],
            "entity_type": "repo",
            "reason": f"org_expansion: {repo['expanded_from_org']}",
            "source": "org_expansion",
            "expanded_from_org": repo["expanded_from_org"],
            "stars": repo["stars"],
            "description": repo["description"],
            "language": repo["language"],
            "llm_note": "",
        })

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        for row in output_rows:
            writer.writerow({k: row.get(k, "") for k in output_fields})

    if args.summary:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Repo Expansion Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Original repos (repo.csv):  {len(original_repos)}", file=sys.stderr)
        print(f"  New repos (org expansion):  {len(expanded_repos)}", file=sys.stderr)
        print(f"  Total in repo_exp.csv:      {len(output_rows)}", file=sys.stderr)
        print(f"  Filter: stars > {args.min_stars} AND active in last year", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)

        from collections import Counter
        org_counts = Counter(r["expanded_from_org"] for r in expanded_repos)
        print(f"\n  Repos by organization:", file=sys.stderr)
        for org, count in org_counts.most_common():
            print(f"    {org:40s} +{count} repos", file=sys.stderr)


if __name__ == "__main__":
    main()
