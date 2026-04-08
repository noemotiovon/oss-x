#!/usr/bin/env python3
"""
Expand verified organizations into their individual repos (Step ⑥).

Reads output/organizations.csv (human-verified organizations from step ③),
queries GitHub API for each org's repos, filters for actively maintained or
widely used repos, deduplicates, and outputs org_expanded_repos.csv.

Requirements:
  - GITHUB_TOKEN env var (optional but recommended to avoid rate limits)
  - Python 3.10+

Usage:
  python3 scripts/expand_orgs.py output/organizations.csv -o output/org_expanded_repos.csv --summary
  python3 scripts/expand_orgs.py output/organizations.csv --existing output/all_repos.csv -o output/org_expanded_repos.csv
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Repos inactive for this many days are considered stale
STALE_DAYS = 365

# Minimum stars to include a repo even if inactive
MIN_STARS_ALWAYS_INCLUDE = 500

# Minimum stars for active repos
MIN_STARS_ACTIVE = 10

# Maximum repos to fetch per org (pagination limit)
MAX_PAGES = 10
PER_PAGE = 100

# Rate limit tracking
_rate_remaining = None
_rate_reset = None


def github_api(endpoint: str) -> dict | list | None:
    """Make a GitHub API request. Returns parsed JSON or None on error."""
    global _rate_remaining, _rate_reset

    url = f"https://api.github.com{endpoint}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oss-x-expand-orgs",
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
            print(f"  Not found: {url}", file=sys.stderr)
        else:
            print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  Network error: {e.reason}", file=sys.stderr)
        return None


def list_org_repos(org: str) -> list[dict]:
    """List all public repos for a GitHub org, paginated."""
    all_repos = []
    for page in range(1, MAX_PAGES + 1):
        endpoint = f"/orgs/{org}/repos?type=public&sort=updated&per_page={PER_PAGE}&page={page}"
        data = github_api(endpoint)
        if not data:
            break
        all_repos.extend(data)
        if len(data) < PER_PAGE:
            break
    return all_repos


def is_repo_relevant(repo: dict,
                      min_stars_active: int = MIN_STARS_ACTIVE,
                      min_stars_popular: int = MIN_STARS_ALWAYS_INCLUDE) -> bool:
    """
    Filter repos: keep those that are actively developed or widely used.

    Criteria:
      - Not archived
      - Not a fork (unless very popular)
      - Either:
        a) Has >= min_stars_popular stars (always include), OR
        b) Has >= min_stars_active stars AND was pushed to within STALE_DAYS
    """
    if repo.get("archived", False):
        return False

    stars = repo.get("stargazers_count", 0)

    # Always include highly starred repos
    if stars >= min_stars_popular:
        return True

    # Skip forks with low stars
    if repo.get("fork", False) and stars < min_stars_popular:
        return False

    # Check activity
    if stars < min_stars_active:
        return False

    pushed_at = repo.get("pushed_at")
    if pushed_at:
        try:
            pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - pushed).days
            if age_days > STALE_DAYS:
                return False
        except (ValueError, TypeError):
            pass

    return True


def normalize_repo_url(url: str) -> str:
    """Normalize a GitHub repo URL for deduplication."""
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return f"https://{parsed.hostname}/{parts[0]}/{parts[1]}".lower()
    return url.lower()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Expand verified organizations into individual repos (step ⑥)"
    )
    parser.add_argument("csv_file", help="Path to organizations.csv")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--existing", help="Path to all_repos.csv for dedup against existing repos")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    parser.add_argument("--min-stars", type=int, default=MIN_STARS_ACTIVE,
                        help=f"Minimum stars for active repos (default: {MIN_STARS_ACTIVE})")
    parser.add_argument("--min-stars-popular", type=int, default=MIN_STARS_ALWAYS_INCLUDE,
                        help=f"Stars threshold to always include (default: {MIN_STARS_ALWAYS_INCLUDE})")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    min_stars_active = args.min_stars
    min_stars_popular = args.min_stars_popular

    # --- Read organizations.csv ---
    orgs = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            orgs.append(row)

    # --- Load existing repo URLs for dedup ---
    seen_urls = set()
    if args.existing:
        with open(args.existing, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                url = row.get("上游地址", "")
                urls = re.findall(r'https?://[^\s,;"]+', url)
                for u in urls:
                    seen_urls.add(normalize_repo_url(u))
        print(f"Loaded {len(seen_urls)} existing repo URLs for dedup", file=sys.stderr)

    # --- Filter to GitHub orgs only; collect non-GitHub for LLM fallback ---
    github_orgs = []
    non_github_orgs = []

    for row in orgs:
        platform = row.get("platform", "").strip()
        owner = row.get("owner", "").strip()
        owner_type = row.get("owner_type", "").strip()

        # Only expand organizations on github.com
        if platform == "github.com" and owner and owner_type == "organization":
            github_orgs.append(row)
        elif owner_type in ("non_github", "manual_review"):
            non_github_orgs.append(row)
        # Skip users — they're not organizations to expand

    print(f"Organizations to expand: {len(github_orgs)} GitHub, {len(non_github_orgs)} non-GitHub",
          file=sys.stderr)

    # --- Expand each org via GitHub API ---
    output_fieldnames = [
        "页签", "项目名称", "分类", "上游地址", "entity_type", "reason",
        "source_org", "stars", "description", "pushed_at",
    ]
    expanded_repos = []
    expand_stats = {}  # org -> (total, filtered, included)

    for row in github_orgs:
        owner = row["owner"]
        name = row.get("name", owner)
        页签 = row.get("页签", "")
        分类 = row.get("分类", "")

        print(f"Expanding org '{name}' (github.com/{owner})...", file=sys.stderr)

        repos = list_org_repos(owner)
        if not repos:
            print(f"  No repos found or API error for {owner}", file=sys.stderr)
            expand_stats[f"{name} ({owner})"] = (0, 0, 0)
            continue

        total = len(repos)
        included = 0

        for repo in repos:
            if not is_repo_relevant(repo, min_stars_active, min_stars_popular):
                continue

            repo_url = repo.get("html_url", "")
            normalized = normalize_repo_url(repo_url)

            if normalized in seen_urls:
                continue

            seen_urls.add(normalized)
            included += 1

            expanded_repos.append({
                "页签": 页签,
                "项目名称": repo.get("name", ""),
                "分类": 分类,
                "上游地址": repo_url,
                "entity_type": "repo",
                "reason": f"组织展开: {name} (github.com/{owner}), ⭐{repo.get('stargazers_count', 0)}",
                "source_org": name,
                "stars": repo.get("stargazers_count", 0),
                "description": repo.get("description") or "",
                "pushed_at": repo.get("pushed_at", ""),
            })

        expand_stats[f"{name} ({owner})"] = (total, total - included, included)
        print(f"  {total} total repos → {included} included", file=sys.stderr)

    # --- Output ---
    if args.json:
        print(json.dumps(expanded_repos, ensure_ascii=False, indent=2))
    else:
        out = sys.stdout
        if args.output:
            out = open(args.output, "w", encoding="utf-8", newline="")

        writer = csv.DictWriter(out, fieldnames=output_fieldnames)
        writer.writeheader()
        for row in expanded_repos:
            writer.writerow(row)

        if args.output:
            out.close()

    # --- Summary ---
    if args.summary:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Org Expansion Summary (Step ⑥)", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Organizations in input:         {len(orgs)}", file=sys.stderr)
        print(f"  GitHub orgs expanded:           {len(github_orgs)}", file=sys.stderr)
        print(f"  Non-GitHub orgs (skipped):      {len(non_github_orgs)}", file=sys.stderr)
        print(f"  New repos discovered:           {len(expanded_repos)}", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)
        print(f"  Expansion details:", file=sys.stderr)
        for name, (total, filtered, included) in expand_stats.items():
            print(f"    {name}: {total} total → {included} included ({filtered} filtered)",
                  file=sys.stderr)
        if non_github_orgs:
            print(f"\n  Non-GitHub orgs (need LLM fallback):", file=sys.stderr)
            for row in non_github_orgs:
                print(f"    - {row.get('name', '?')}: {row.get('url', '?')}", file=sys.stderr)

    # Exit with code 1 if there are non-GitHub orgs needing manual handling
    sys.exit(1 if non_github_orgs else 0)


if __name__ == "__main__":
    main()
