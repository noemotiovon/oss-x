#!/usr/bin/env python3
"""
Data cleaning & URL validation (Step 0).

For each row in data.csv:
  1. Parse and normalize the URL field
  2. Validate GitHub URLs via API (repos and orgs)
  3. For valid GitHub repos: fetch open_issues_count, total PR count, fork/archived/mirror status
  4. Flag non-GitHub URLs and invalid entries for manual review

Output: cleaned.csv with validation status and repo activity metrics.

Requirements:
  - GITHUB_TOKEN env var (required for reasonable rate limits)
  - Python 3.10+

Usage:
  python3 scripts/clean.py data.csv -o output/cleaned.csv --summary
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

# ---------------------------------------------------------------------------
# GitHub API helpers (reused pattern from resolve_orgs.py)
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

CACHE_DIR = Path("output/.cache")
CACHE_FILE = CACHE_DIR / "github_clean_cache.json"

_rate_remaining = None
_rate_reset = None


def _interruptible_wait(seconds: int, label: str = "Rate limit reset") -> None:
    """Sleep in small increments with countdown, allowing Ctrl-C to interrupt."""
    end_time = time.time() + seconds
    while True:
        remaining = int(end_time - time.time())
        if remaining <= 0:
            break
        print(f"\r  ⏳ {label}: {remaining}s remaining (Ctrl-C to abort)  ",
              end="", file=sys.stderr, flush=True)
        time.sleep(min(5, remaining))
    print(f"\r  ✓ {label} complete.{' ' * 40}", file=sys.stderr)


def _load_cache() -> dict:
    """Load previously validated URLs from disk cache."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"  Loaded {len(data)} cached validations from {CACHE_FILE}", file=sys.stderr)
            return data
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Warning: cache file corrupt ({e}), ignoring", file=sys.stderr)
    return {}


def _save_cache(cache: dict) -> None:
    """Persist validated URLs to disk cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    tmp.replace(CACHE_FILE)


def github_api(endpoint: str, parse_link: bool = False) -> dict | list | None:
    """
    Make a GitHub API request. Returns parsed JSON or None on error.
    If parse_link=True, returns (json, last_page) tuple.
    """
    global _rate_remaining, _rate_reset

    url = f"https://api.github.com{endpoint}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oss-x-clean",
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
            body = json.loads(resp.read().decode())
            if parse_link:
                link_header = resp.headers.get("Link", "")
                last_page = _parse_last_page(link_header)
                return body, last_page
            return body
    except HTTPError as e:
        if e.code == 403:
            reset = e.headers.get("X-RateLimit-Reset")
            if reset:
                wait = int(reset) - int(time.time()) + 1
                if wait > 0:
                    _interruptible_wait(wait, "403 rate-limit retry")
                    return github_api(endpoint, parse_link)
            else:
                print(f"  403 Forbidden: {url}", file=sys.stderr)
        elif e.code == 404:
            if parse_link:
                return None, 0
            return None
        elif e.code == 422:
            # Unprocessable — e.g., repo exists but issues/PRs disabled
            if parse_link:
                return None, 0
            return None
        else:
            print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        if parse_link:
            return None, 0
        return None
    except URLError as e:
        print(f"  Network error: {e.reason}", file=sys.stderr)
        if parse_link:
            return None, 0
        return None


def _parse_last_page(link_header: str) -> int:
    """Parse Link header to find last page number (for total count estimation)."""
    if not link_header:
        return 0
    # Look for: <...?page=N>; rel="last"
    match = re.search(r'<[^>]*[?&]page=(\d+)[^>]*>;\s*rel="last"', link_header)
    if match:
        return int(match.group(1))
    return 0


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def extract_urls(raw: str) -> list[str]:
    """Extract all URLs from a field (may contain multiple URLs or newlines)."""
    return [u.strip().rstrip("/") for u in re.findall(r'https?://[^\s,;"]+', raw)]


def parse_github_url(url: str) -> dict | None:
    """
    Parse a GitHub URL into components.
    Returns {"owner": ..., "repo": ...} or {"owner": ...} or None.
    """
    parsed = urlparse(url.strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    if host != "github.com":
        return None

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return {"owner": parts[0], "repo": parts[1]}
    elif len(parts) == 1:
        return {"owner": parts[0]}
    return None


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

_EXTRA_FIELDS = [
    "stars", "forks", "watchers", "open_issues_count", "total_pull_requests",
    "language", "license", "created_at", "updated_at", "pushed_at",
    "size_kb", "default_branch", "topics", "fork", "archived", "mirror_url", "has_issues",
]


def _empty_result(status: str, url_type: str) -> dict:
    """Return a result dict with all metric fields blank."""
    r = {"status": status, "url_type": url_type, "actual_url": ""}
    for f in _EXTRA_FIELDS:
        r[f] = ""
    return r


def validate_github_repo(owner: str, repo: str, cache: dict) -> dict:
    """
    Validate a GitHub repo and collect activity metrics.
    Returns dict with validation result.
    """
    cache_key = f"repo:{owner}/{repo}"
    if cache_key in cache:
        return cache[cache_key]

    print(f"  Validating repo: {owner}/{repo}", file=sys.stderr)
    data = github_api(f"/repos/{owner}/{repo}")

    if data is None:
        result = _empty_result("not_found", "repo")
        cache[cache_key] = result
        _save_cache(cache)
        return result

    # The API may return a different full_name if the repo was renamed/transferred
    actual_full_name = data.get("full_name", f"{owner}/{repo}")
    actual_url = f"https://github.com/{actual_full_name}"

    # Get total PR count via pagination
    _, last_page = github_api(
        f"/repos/{actual_full_name}/pulls?state=all&per_page=1",
        parse_link=True,
    )
    # If last_page is 0 but we got a response, check if there are 0 or 1 PRs
    if last_page == 0:
        # Make the call again without parse_link to check the body
        pr_data = github_api(f"/repos/{actual_full_name}/pulls?state=all&per_page=1")
        total_prs = len(pr_data) if isinstance(pr_data, list) else 0
    else:
        total_prs = last_page

    # Extract license name
    license_info = data.get("license")
    license_name = license_info.get("spdx_id", "") if isinstance(license_info, dict) else ""

    result = {
        "status": "valid",
        "url_type": "repo",
        "actual_url": actual_url if actual_url != f"https://github.com/{owner}/{repo}" else "",
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "watchers": data.get("subscribers_count", 0),
        "open_issues_count": data.get("open_issues_count", 0),
        "total_pull_requests": total_prs,
        "language": data.get("language") or "",
        "license": license_name,
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
        "pushed_at": data.get("pushed_at", ""),
        "size_kb": data.get("size", 0),
        "default_branch": data.get("default_branch", ""),
        "topics": ",".join(data.get("topics", [])),
        "fork": data.get("fork", False),
        "archived": data.get("archived", False),
        "mirror_url": data.get("mirror_url") or "",
        "has_issues": data.get("has_issues", True),
    }

    cache[cache_key] = result
    _save_cache(cache)
    return result


def validate_github_org(owner: str, cache: dict) -> dict:
    """Validate a GitHub organization."""
    cache_key = f"org:{owner}"
    if cache_key in cache:
        return cache[cache_key]

    print(f"  Validating org: {owner}", file=sys.stderr)
    data = github_api(f"/orgs/{owner}")

    if data is None:
        # Could be a user account, not an org
        user_data = github_api(f"/users/{owner}")
        if user_data is not None:
            result = _empty_result("valid_user", "user")
        else:
            result = _empty_result("not_found", "org")
        cache[cache_key] = result
        _save_cache(cache)
        return result

    result = _empty_result("valid", "org")
    cache[cache_key] = result
    _save_cache(cache)
    return result


def validate_row(name: str, url_field: str, cache: dict) -> dict:
    """
    Validate a single row from data.csv.
    Returns validation result dict.
    """
    urls = extract_urls(url_field)

    # No URL at all
    if not urls:
        result = _empty_result("no_url", "")
        result["note"] = f"无有效URL: {url_field}" if url_field.strip() else "URL为空"
        return result

    # Multiple URLs — flag for review but try to validate the first one
    note = ""
    if len(urls) > 1:
        note = f"多个URL({len(urls)}个), 仅验证第一个"

    url = urls[0]
    gh = parse_github_url(url)

    if gh is None:
        # Non-GitHub URL
        result = _empty_result("non_github", "non_github")
        result["note"] = note or "非GitHub URL"
        return result

    if "repo" in gh:
        result = validate_github_repo(gh["owner"], gh["repo"], cache)
    else:
        result = validate_github_org(gh["owner"], cache)

    result["note"] = note
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Clean and validate data.csv URLs")
    parser.add_argument("csv_file", help="Path to input CSV file")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    args = parser.parse_args()

    if not GITHUB_TOKEN:
        print("Warning: GITHUB_TOKEN not set, API rate limits will be very low (60/hour)",
              file=sys.stderr)

    cache = _load_cache()

    # Read input
    rows = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        input_fields = reader.fieldnames
        for row in reader:
            rows.append(row)

    print(f"Processing {len(rows)} entries...", file=sys.stderr)

    # Validate each row
    results = []
    for i, row in enumerate(rows):
        name = row.get("项目名称", "").strip()
        url_field = row.get("上游地址", "").strip()

        if not name and not url_field:
            continue

        validation = validate_row(name, url_field, cache)

        result = {
            "页签": row.get("页签", ""),
            "序号": row.get("序号", ""),
            "项目名称": name,
            "分类": row.get("分类", ""),
            "上游地址": url_field,
            "status": validation["status"],
            "url_type": validation["url_type"],
            "actual_url": validation.get("actual_url", ""),
            "stars": validation.get("stars", ""),
            "forks": validation.get("forks", ""),
            "watchers": validation.get("watchers", ""),
            "open_issues_count": validation.get("open_issues_count", ""),
            "total_pull_requests": validation.get("total_pull_requests", ""),
            "language": validation.get("language", ""),
            "license": validation.get("license", ""),
            "created_at": validation.get("created_at", ""),
            "updated_at": validation.get("updated_at", ""),
            "pushed_at": validation.get("pushed_at", ""),
            "size_kb": validation.get("size_kb", ""),
            "default_branch": validation.get("default_branch", ""),
            "topics": validation.get("topics", ""),
            "fork": validation.get("fork", ""),
            "archived": validation.get("archived", ""),
            "mirror_url": validation.get("mirror_url", ""),
            "has_issues": validation.get("has_issues", ""),
            "note": validation.get("note", ""),
        }
        results.append(result)

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(rows)}", file=sys.stderr)

    # Write output
    out_fields = [
        "页签", "序号", "项目名称", "分类", "上游地址",
        "status", "url_type", "actual_url",
        "stars", "forks", "watchers",
        "open_issues_count", "total_pull_requests",
        "language", "license",
        "created_at", "updated_at", "pushed_at",
        "size_kb", "default_branch", "topics",
        "fork", "archived", "mirror_url", "has_issues", "note",
    ]

    out = sys.stdout
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        out = open(args.output, "w", encoding="utf-8", newline="")

    writer = csv.DictWriter(out, fieldnames=out_fields)
    writer.writeheader()
    for r in results:
        writer.writerow(r)

    if args.output:
        out.close()
        print(f"\nOutput written to {args.output}", file=sys.stderr)

    # Summary
    if args.summary:
        from collections import Counter
        statuses = Counter(r["status"] for r in results)
        total = len(results)
        print(f"\n--- Validation Summary ({total} entries) ---", file=sys.stderr)
        for status, count in statuses.most_common():
            print(f"  {status:15s}: {count:4d} ({count/total*100:.1f}%)", file=sys.stderr)

        # Flag potential mirrors (valid repos with 0 PRs and issues disabled)
        mirrors = [r for r in results
                   if r["status"] == "valid"
                   and r["url_type"] == "repo"
                   and r["total_pull_requests"] == 0
                   and r["has_issues"] is False]
        if mirrors:
            print(f"\n⚠ Potential mirror repos (0 PRs, issues disabled): {len(mirrors)}", file=sys.stderr)
            for r in mirrors:
                print(f"  - {r['项目名称']:30s} | {r['上游地址']}", file=sys.stderr)

        # Flag not found
        not_found = [r for r in results if r["status"] == "not_found"]
        if not_found:
            print(f"\n✗ Not found ({len(not_found)}):", file=sys.stderr)
            for r in not_found:
                print(f"  - {r['项目名称']:30s} | {r['上游地址']}", file=sys.stderr)

        # Flag non-GitHub
        non_gh = [r for r in results if r["status"] == "non_github"]
        if non_gh:
            print(f"\n⚠ Non-GitHub URLs ({len(non_gh)}) — need manual review:", file=sys.stderr)
            for r in non_gh:
                print(f"  - {r['项目名称']:30s} | {r['上游地址']}", file=sys.stderr)

        # Flag no URL
        no_url = [r for r in results if r["status"] == "no_url"]
        if no_url:
            print(f"\n✗ No valid URL ({len(no_url)}):", file=sys.stderr)
            for r in no_url:
                print(f"  - {r['项目名称']:30s} | {r['note']}", file=sys.stderr)

        # Flag repos that were redirected (transferred/renamed)
        redirected = [r for r in results if r["actual_url"]]
        if redirected:
            print(f"\n↪ Redirected repos ({len(redirected)}) — URL has changed:", file=sys.stderr)
            for r in redirected:
                print(f"  - {r['项目名称']:30s} | {r['上游地址']} → {r['actual_url']}", file=sys.stderr)

        # Flag archived repos
        archived = [r for r in results if r["archived"] is True]
        if archived:
            print(f"\n📦 Archived repos ({len(archived)}):", file=sys.stderr)
            for r in archived:
                print(f"  - {r['项目名称']:30s} | {r['上游地址']}", file=sys.stderr)


if __name__ == "__main__":
    main()
