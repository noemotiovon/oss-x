#!/usr/bin/env python3
"""
Merge repo sources into a unified all_repos.csv.

Combines:
  - output/repos.csv (from step ①)
  - output/non_repos_classified.csv rows where entity_type=repo (from step ②)

Deduplicates by normalized URL (case-insensitive, strips .git and trailing paths).

Usage:
  python3 scripts/merge_repos.py output/repos.csv output/non_repos_classified.csv \
      -o output/all_repos.csv --summary
"""

import argparse
import csv
import re
import sys
from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    """Normalize a repo URL for deduplication."""
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if parsed.hostname and len(parts) >= 2:
        return f"https://{parsed.hostname}/{parts[0]}/{parts[1]}".lower()
    return url.lower()


def extract_urls(raw: str) -> list[str]:
    """Extract all URLs from a field."""
    return [u.strip() for u in re.findall(r'https?://[^\s,;"]+', raw)]


def main():
    parser = argparse.ArgumentParser(description="Merge repo sources into all_repos.csv")
    parser.add_argument("repos_csv", help="Path to repos.csv (step ① output)")
    parser.add_argument("non_repos_classified_csv", nargs="?",
                        help="Path to non_repos_classified.csv (step ② output, optional)")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    args = parser.parse_args()

    fieldnames = ["页签", "序号", "项目名称", "分类", "上游地址", "entity_type", "reason"]
    seen_urls = set()
    output_rows = []
    stats = {"repos_csv": 0, "non_repos_csv": 0, "duplicates": 0}

    # Read repos.csv
    with open(args.repos_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url_field = row.get("上游地址", "")
            urls = extract_urls(url_field)
            normalized = normalize_url(urls[0]) if urls else url_field.lower()
            if normalized in seen_urls:
                stats["duplicates"] += 1
                continue
            seen_urls.add(normalized)
            output_rows.append(row)
            stats["repos_csv"] += 1

    # Read non_repos_classified.csv (only type=repo rows)
    if args.non_repos_classified_csv:
        with open(args.non_repos_classified_csv, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("entity_type", "").strip() != "repo":
                    continue
                url_field = row.get("上游地址", "")
                urls = extract_urls(url_field)
                normalized = normalize_url(urls[0]) if urls else url_field.lower()
                if normalized in seen_urls:
                    stats["duplicates"] += 1
                    continue
                seen_urls.add(normalized)
                output_rows.append(row)
                stats["non_repos_csv"] += 1

    # Output
    out = sys.stdout
    if args.output:
        out = open(args.output, "w", encoding="utf-8", newline="")

    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in output_rows:
        writer.writerow(row)

    if args.output:
        out.close()

    if args.summary:
        total = len(output_rows)
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Merge Repos Summary", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        print(f"  From repos.csv:               {stats['repos_csv']}", file=sys.stderr)
        print(f"  From non_repos_classified.csv: {stats['non_repos_csv']}", file=sys.stderr)
        print(f"  Duplicates removed:            {stats['duplicates']}", file=sys.stderr)
        print(f"  Total in all_repos.csv:        {total}", file=sys.stderr)


if __name__ == "__main__":
    main()
