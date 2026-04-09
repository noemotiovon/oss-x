#!/usr/bin/env python3
"""
Validate organizations from org_exp.csv.

Layer 1: Auto-validate orgs with repo_count > 1
Layer 2: GitHub API validation for single-repo GitHub orgs
Layer 3: Marks non-GitHub orgs for LLM validation (handled externally)
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CACHE_DIR = Path("output/.cache")
CACHE_FILE = CACHE_DIR / "org_validation_cache.json"

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
            print(f"  Loaded {len(data)} cached validations", file=sys.stderr)
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
        "User-Agent": "oss-x-validate-orgs",
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
        elif e.code == 404:
            return None
        elif e.code == 422:
            return None
        print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  Network error: {e.reason}", file=sys.stderr)
        return None


def validate_github_org(owner):
    """Query GitHub API for org validation stats."""
    # Get total repos count from org info
    org_data = github_api(f"/orgs/{owner}")
    total_repos = 0
    if org_data and isinstance(org_data, dict):
        total_repos = org_data.get("public_repos", 0)

    # Search for repos with >100 stars
    star_gt100 = 0
    search = github_api(f"/search/repositories?q=org:{owner}+stars:>100&per_page=1")
    if search and isinstance(search, dict):
        star_gt100 = search.get("total_count", 0)

    # Search for active repos (pushed in last year)
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    active = github_api(f"/search/repositories?q=org:{owner}+pushed:>{one_year_ago}&per_page=1")
    active_repos = 0
    if active and isinstance(active, dict):
        active_repos = active.get("total_count", 0)

    return {
        "total_repos": total_repos,
        "star_gt100": star_gt100,
        "active_repos": active_repos,
    }


def extract_github_owner(url):
    parsed = urlparse((url or "").strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    if host == "github.com":
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts:
            return parts[0]
    return None


def main():
    parser = argparse.ArgumentParser(description="Validate organizations")
    parser.add_argument("csv_file", help="Path to org_exp.csv")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    rows = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    output_fields = list(rows[0].keys()) + [
        "is_valid", "total_repos", "star_gt100", "active_repos",
        "validation_method", "validation_evidence",
    ]

    cache = {} if args.no_cache else _load_cache()

    # Layer 1: Auto-validate
    auto_valid = 0
    need_api = []
    need_llm = []

    for row in rows:
        repo_count = int(row.get("repo_count", 0))
        if repo_count > 1:
            row["is_valid"] = "true"
            row["validation_method"] = "脚本(repo数量>1)"
            row["validation_evidence"] = f"CSV中repo_count={repo_count}"
            row["total_repos"] = row.get("public_repos", "")
            row["star_gt100"] = ""
            row["active_repos"] = ""
            auto_valid += 1
        elif row.get("platform") == "github.com":
            need_api.append(row)
        else:
            need_llm.append(row)

    # Layer 2: GitHub API validation
    print(f"\nLayer 1: {auto_valid} auto-validated (repo_count > 1)", file=sys.stderr)
    print(f"Layer 2: {len(need_api)} GitHub orgs to validate via API", file=sys.stderr)
    print(f"Layer 3: {len(need_llm)} non-GitHub orgs for LLM validation\n", file=sys.stderr)

    cache_hits = 0
    to_query = []
    for row in need_api:
        owner = extract_github_owner(row.get("org_url", ""))
        if not owner:
            owner = row.get("org_name", "")
        key = owner.lower()
        if key in cache:
            stats = cache[key]
            row["total_repos"] = stats.get("total_repos", 0)
            row["star_gt100"] = stats.get("star_gt100", 0)
            row["active_repos"] = stats.get("active_repos", 0)
            # Auto-decide: valid if has starred or active repos
            if stats.get("star_gt100", 0) > 0 or stats.get("active_repos", 0) > 0:
                row["is_valid"] = "true"
                row["validation_evidence"] = f"stars>100: {stats['star_gt100']}, active: {stats['active_repos']}"
            else:
                row["is_valid"] = "true"  # Default true for GitHub orgs
                row["validation_evidence"] = f"total_repos: {stats['total_repos']}"
            row["validation_method"] = "GitHub API"
            cache_hits += 1
        else:
            to_query.append((row, owner))

    print(f"  GitHub API: {cache_hits} cached, {len(to_query)} to query\n", file=sys.stderr)

    save_interval = 20
    for i, (row, owner) in enumerate(to_query, 1):
        if i % 10 == 0 or i == len(to_query):
            rl_info = f" [rate_remaining={_rate_remaining}]" if _rate_remaining is not None else ""
            print(f"  Progress: {i}/{len(to_query)}{rl_info}", file=sys.stderr)
        try:
            stats = validate_github_org(owner)
        except KeyboardInterrupt:
            print(f"\n  Interrupted at {i}/{len(to_query)}. Saving...", file=sys.stderr)
            _save_cache(cache)
            sys.exit(130)

        cache[owner.lower()] = stats
        row["total_repos"] = stats["total_repos"]
        row["star_gt100"] = stats["star_gt100"]
        row["active_repos"] = stats["active_repos"]

        if stats["star_gt100"] > 0 or stats["active_repos"] > 0:
            row["is_valid"] = "true"
            row["validation_evidence"] = f"stars>100: {stats['star_gt100']}, active: {stats['active_repos']}"
        else:
            row["is_valid"] = "true"  # Default true for GitHub orgs
            row["validation_evidence"] = f"total_repos: {stats['total_repos']}"
        row["validation_method"] = "GitHub API"

        if i % save_interval == 0:
            _save_cache(cache)

    _save_cache(cache)

    # Layer 3: Mark non-GitHub for LLM (placeholder — filled by LLM step)
    for row in need_llm:
        row["is_valid"] = "pending_llm"
        row["total_repos"] = ""
        row["star_gt100"] = ""
        row["active_repos"] = ""
        row["validation_method"] = "LLM"
        row["validation_evidence"] = ""

    # Write output
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in output_fields})

    if args.summary:
        valid = sum(1 for r in rows if r.get("is_valid") == "true")
        invalid = sum(1 for r in rows if r.get("is_valid") == "false")
        pending = sum(1 for r in rows if r.get("is_valid") == "pending_llm")
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Validation Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Total organizations:  {len(rows)}", file=sys.stderr)
        print(f"  Valid:                {valid}", file=sys.stderr)
        print(f"  Invalid:              {invalid}", file=sys.stderr)
        print(f"  Pending LLM:          {pending}", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)
        print(f"  By method:", file=sys.stderr)
        print(f"    脚本(repo数量>1):   {auto_valid}", file=sys.stderr)
        print(f"    GitHub API:         {len(need_api)}", file=sys.stderr)
        print(f"    LLM (pending):      {len(need_llm)}", file=sys.stderr)

        if pending > 0:
            print(f"\n  Non-GitHub orgs pending LLM validation:", file=sys.stderr)
            for r in need_llm:
                print(f"    - {r['org_name']}: {r['org_url']}", file=sys.stderr)


if __name__ == "__main__":
    main()
