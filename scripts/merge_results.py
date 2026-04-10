#!/usr/bin/env python3
"""
Step ⑪ — Merge repo_exp, foundation, and company into result.csv

Usage:
    python3 scripts/merge_results.py \
        output/repo_exp.csv \
        output/foundation.csv \
        output/company.csv \
        -o output/result.csv \
        --summary
"""
import argparse
import csv
import sys
from urllib.parse import urlparse


def extract_org(url: str) -> str:
    """Extract GitHub org name from a repo URL."""
    try:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2:
            return parts[0]
    except Exception:
        pass
    return ""


def load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description="Merge repo_exp, foundation, company → result.csv")
    parser.add_argument("repo_exp", help="output/repo_exp.csv")
    parser.add_argument("foundation", help="output/foundation.csv")
    parser.add_argument("company", help="output/company.csv")
    parser.add_argument("-o", "--output", default="output/result.csv", help="Output file path")
    parser.add_argument("--summary", action="store_true", help="Print summary after merge")
    args = parser.parse_args()

    repos = load_csv(args.repo_exp)
    foundations = load_csv(args.foundation)
    companies = load_csv(args.company)

    # Build lookup by URL
    foundation_map: dict[str, str] = {}
    for row in foundations:
        url = row.get("上游地址", "").strip()
        name = row.get("foundation_name", "none").strip()
        if url:
            foundation_map[url] = name

    company_map: dict[str, str] = {}
    for row in companies:
        url = row.get("上游地址", "").strip()
        name = row.get("company_name", "unknown").strip()
        if url:
            company_map[url] = name

    output_rows = []
    for repo in repos:
        url = repo.get("上游地址", "").strip()
        output_rows.append({
            "页签": repo.get("页签", ""),
            "项目名称": repo.get("项目名称", ""),
            "repo": url,
            "organization": extract_org(url),
            "foundation": foundation_map.get(url, "none"),
            "company": company_map.get(url, "unknown"),
        })

    fieldnames = ["页签", "项目名称", "repo", "organization", "foundation", "company"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    if args.summary:
        total = len(output_rows)
        with_foundation = sum(1 for r in output_rows if r["foundation"] not in ("none", "unknown", ""))
        with_company = sum(1 for r in output_rows if r["company"] not in ("none", "unknown", ""))

        tab_counts: dict[str, int] = {}
        for r in output_rows:
            tab = r["页签"] or "(无页签)"
            tab_counts[tab] = tab_counts.get(tab, 0) + 1

        print(f"\n=== Merge Results Summary ===")
        print(f"Total repos:            {total}")
        print(f"With foundation:        {with_foundation}")
        print(f"With company:           {with_company}")
        print(f"\nBreakdown by 页签:")
        for tab, count in sorted(tab_counts.items()):
            print(f"  {tab}: {count}")
        print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
