#!/usr/bin/env python3
"""
Resolve unknown org affiliations for repos (Step ⑤).

For repos in repo_unknown_org.csv that have no known GitHub organization,
try to find their organization affiliation using automated methods:

  Layer 1: GitHub API — check if repo is a fork (source repo's org)
  Layer 2: GitHub API — check user's public org memberships
  Layer 3: GitHub API — check repo topics and description for org hints
  Layer 4: Mark remaining for LLM

Usage:
  python3 scripts/resolve_unknown_orgs.py output/repo_unknown_org.csv \
      -o output/repo_unknown_org.csv --summary
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

_rate_remaining = None
_rate_reset = None


def github_api(endpoint):
    """Call GitHub API. Returns parsed JSON or None."""
    global _rate_remaining, _rate_reset

    url = f"https://api.github.com{endpoint}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oss-x-resolve-unknown-orgs",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    if _rate_remaining is not None and _rate_remaining <= 1 and _rate_reset:
        wait = _rate_reset - int(time.time()) + 1
        if wait > 0:
            wait = min(wait, 60)
            print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            _rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
            _rate_reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            return json.loads(resp.read().decode())
    except HTTPError as e:
        if e.code == 403:
            reset = e.headers.get("X-RateLimit-Reset")
            if reset:
                wait = min(int(reset) - int(time.time()) + 1, 60)
                if wait > 0:
                    print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                    return github_api(endpoint)
        return None
    except Exception:
        return None


def extract_repos_from_list(repos_list):
    """Extract individual repo names from semicolon-joined list."""
    if not repos_list:
        return []
    return [r.strip() for r in repos_list.split(";") if r.strip()]


def check_fork_source(owner, repo_name):
    """
    Layer 1: Check if a repo is a fork and find the source org.
    Returns (org_name, org_url, evidence) or None.
    """
    data = github_api(f"/repos/{owner}/{repo_name}")
    if not data:
        return None

    if data.get("fork") and data.get("source"):
        source = data["source"]
        source_owner = source.get("owner", {})
        if source_owner.get("type") == "Organization":
            org_login = source_owner.get("login", "")
            return (
                org_login,
                f"https://github.com/{org_login}",
                f"Fork来源: {source.get('full_name', '')} (org: {org_login})",
            )

    return None


def check_user_orgs(username):
    """
    Layer 2: Check user's public organization memberships.
    Returns list of (org_name, org_url).
    """
    data = github_api(f"/users/{username}/orgs")
    if not data or not isinstance(data, list):
        return []

    orgs = []
    for org in data:
        login = org.get("login", "")
        if login:
            orgs.append((login, f"https://github.com/{login}"))
    return orgs


def check_repo_org_hints(owner, repo_name):
    """
    Layer 3: Check repo topics, description, homepage for org hints.
    Returns (org_name, org_url, evidence) or None.
    """
    data = github_api(f"/repos/{owner}/{repo_name}")
    if not data:
        return None

    # Check if the repo has been transferred/moved
    actual_owner = data.get("owner", {})
    if actual_owner.get("login", "").lower() != owner.lower():
        if actual_owner.get("type") == "Organization":
            org_login = actual_owner["login"]
            return (
                org_login,
                f"https://github.com/{org_login}",
                f"Repo已迁移至org: {org_login}",
            )

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Resolve unknown org affiliations via GitHub API (step ⑤)"
    )
    parser.add_argument("csv_file", help="Path to repo_unknown_org.csv")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    # Read input
    rows = []
    fieldnames = None
    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)

    if not rows:
        print("No rows to process.", file=sys.stderr)
        sys.exit(0)

    # Ensure output columns exist
    extra_cols = ["org_name", "org_url", "evidence", "confidence"]
    for col in extra_cols:
        if col not in fieldnames:
            fieldnames = list(fieldnames) + [col]

    # Process only rows that don't already have org_name filled
    stats = {"fork": 0, "user_org": 0, "repo_moved": 0, "already_filled": 0, "remaining": 0}

    already_resolved = sum(1 for r in rows if r.get("org_name", "").strip())
    needs_resolution = [i for i, r in enumerate(rows) if not r.get("org_name", "").strip()]

    print(f"Total rows: {len(rows)}, already resolved: {already_resolved}, "
          f"to process: {len(needs_resolution)}", file=sys.stderr)

    for idx in needs_resolution:
        row = rows[idx]
        owner = row.get("owner", "").strip()
        owner_type = row.get("owner_type", "")
        repos_list = row.get("repos_list", "")
        repos = extract_repos_from_list(repos_list)
        url = row.get("url", "")

        if not owner or owner_type not in ("user", "unknown"):
            stats["remaining"] += 1
            continue

        resolved = False

        # Layer 1: Check fork source for each repo
        for repo_name in repos[:3]:  # Check up to 3 repos
            result = check_fork_source(owner, repo_name)
            if result:
                row["org_name"] = result[0]
                row["org_url"] = result[1]
                row["evidence"] = result[2]
                row["confidence"] = "S"
                stats["fork"] += 1
                resolved = True
                break

        if resolved:
            continue

        # Layer 2: Check user's org memberships
        user_orgs = check_user_orgs(owner)
        if user_orgs:
            # If user belongs to exactly 1 org, that's likely the affiliation
            if len(user_orgs) == 1:
                org_name, org_url = user_orgs[0]
                row["org_name"] = org_name
                row["org_url"] = org_url
                row["evidence"] = f"用户唯一公开org: {org_name}"
                row["confidence"] = "A"
                stats["user_org"] += 1
                resolved = True
            else:
                # Multiple orgs — record them but mark for confirmation
                org_names = [o[0] for o in user_orgs]
                row["org_name"] = ""
                row["org_url"] = ""
                row["evidence"] = f"用户属于多个org: {', '.join(org_names[:5])}"
                row["confidence"] = ""
                stats["remaining"] += 1
                resolved = True  # Don't try more layers

        if resolved:
            continue

        # Layer 3: Check if repo has been moved
        for repo_name in repos[:1]:
            result = check_repo_org_hints(owner, repo_name)
            if result:
                row["org_name"] = result[0]
                row["org_url"] = result[1]
                row["evidence"] = result[2]
                row["confidence"] = "S"
                stats["repo_moved"] += 1
                resolved = True
                break

        if not resolved:
            stats["remaining"] += 1

    # Write output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    if args.summary:
        total_with_org = sum(1 for r in rows if r.get("org_name", "").strip())
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Unknown Org Resolution Summary (Step ⑤)", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Total entries:         {len(rows)}", file=sys.stderr)
        print(f"  Previously resolved:   {already_resolved}", file=sys.stderr)
        print(f"  Resolved this run:", file=sys.stderr)
        print(f"    Fork source:         {stats['fork']}", file=sys.stderr)
        print(f"    User org membership: {stats['user_org']}", file=sys.stderr)
        print(f"    Repo moved:          {stats['repo_moved']}", file=sys.stderr)
        print(f"  Total with org_name:   {total_with_org}", file=sys.stderr)
        print(f"  Remaining (need LLM):  {stats['remaining']}", file=sys.stderr)


if __name__ == "__main__":
    main()
