#!/usr/bin/env python3
"""
Final merge: combine all pipeline outputs into final.csv (Step ⑧).

Reads:
  - output/all_repos.csv (seed repos)
  - output/org_expanded_repos.csv (step ⑥ expanded repos)
  - output/foundation_expanded_repos.csv (step ⑦ expanded repos)
  - output/organizations.csv (verified organizations)
  - output/companies.csv (companies)
  - output/foundations_deduped.csv (foundations)

Merges, deduplicates by URL, and outputs final.csv.

Usage:
  python3 scripts/merge_final.py -o output/final.csv --summary
"""

import argparse
import csv
import re
import sys
import os
from urllib.parse import urlparse

# Default input paths
DEFAULT_INPUTS = {
    "all_repos": "output/all_repos.csv",
    "org_expanded": "output/org_expanded_repos.csv",
    "foundation_expanded": "output/foundation_expanded_repos.csv",
    "organizations": "output/organizations.csv",
    "companies": "output/companies.csv",
    "foundations": "output/foundations_deduped.csv",
}

# Output columns per design
OUTPUT_FIELDNAMES = [
    "name",
    "url",
    "type",          # repo / organization / company / foundation
    "category",      # original 分类
    "organization",  # parent GitHub org
    "company",       # parent company
    "foundation",    # parent foundation
    "stars",
    "last_active",
    "description",
    "evidence",
]


def normalize_url(url: str) -> str:
    """Normalize URL for dedup."""
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if parsed.hostname and len(parts) >= 2:
        return f"https://{parsed.hostname}/{parts[0]}/{parts[1]}".lower()
    if parsed.hostname and len(parts) == 1:
        return f"https://{parsed.hostname}/{parts[0]}".lower()
    return url.lower()


def read_csv_safe(path: str) -> list[dict]:
    """Read CSV file, return empty list if file doesn't exist."""
    if not os.path.exists(path):
        print(f"  Skipping (not found): {path}", file=sys.stderr)
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_org_lookup(orgs_rows: list[dict]) -> dict:
    """Build owner → org name lookup."""
    lookup = {}
    for row in orgs_rows:
        owner = row.get("owner", "").strip().lower()
        if owner:
            lookup[owner] = row.get("name", row.get("owner", ""))
    return lookup


def build_company_lookup(companies_rows: list[dict]) -> dict:
    """Build org → company lookup."""
    lookup = {}
    for row in companies_rows:
        company = row.get("company", "").strip()
        if not company:
            continue
        orgs = row.get("associated_orgs", "").split(";")
        for org in orgs:
            org = org.strip().lower()
            if org:
                lookup[org] = company
    return lookup


def build_foundation_lookup(foundations_rows: list[dict]) -> dict:
    """Build org → foundation lookup."""
    lookup = {}
    for row in foundations_rows:
        foundation = row.get("foundation", "").strip()
        if not foundation:
            continue
        orgs = row.get("associated_orgs", "").split(";")
        for org in orgs:
            org = org.strip().lower()
            if org:
                lookup[org] = foundation
    return lookup


def extract_owner_from_url(url: str) -> str:
    """Extract GitHub owner from a repo URL."""
    parsed = urlparse(url.strip().rstrip("/"))
    if (parsed.hostname or "").lower() == "github.com":
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts:
            return parts[0].lower()
    return ""


def main():
    parser = argparse.ArgumentParser(description="Final merge into final.csv (step ⑧)")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    # Allow overriding default input paths
    parser.add_argument("--all-repos", default=DEFAULT_INPUTS["all_repos"])
    parser.add_argument("--org-expanded", default=DEFAULT_INPUTS["org_expanded"])
    parser.add_argument("--foundation-expanded", default=DEFAULT_INPUTS["foundation_expanded"])
    parser.add_argument("--organizations", default=DEFAULT_INPUTS["organizations"])
    parser.add_argument("--companies", default=DEFAULT_INPUTS["companies"])
    parser.add_argument("--foundations", default=DEFAULT_INPUTS["foundations"])
    args = parser.parse_args()

    # --- Read all input files ---
    print("Reading input files...", file=sys.stderr)
    all_repos = read_csv_safe(args.all_repos)
    org_expanded = read_csv_safe(args.org_expanded)
    foundation_expanded = read_csv_safe(args.foundation_expanded)
    organizations = read_csv_safe(args.organizations)
    companies = read_csv_safe(args.companies)
    foundations = read_csv_safe(args.foundations)

    # --- Build lookup tables ---
    org_lookup = build_org_lookup(organizations)
    company_lookup = build_company_lookup(companies)
    foundation_lookup = build_foundation_lookup(foundations)

    # --- Process repos (seed + expanded) ---
    seen_urls = set()
    output_rows = []
    stats = {"seed_repos": 0, "org_expanded": 0, "foundation_expanded": 0,
             "organizations": 0, "companies": 0, "foundations": 0, "duplicates": 0}

    def add_repo(row: dict, source: str):
        url = row.get("上游地址", "").strip()
        urls = re.findall(r'https?://[^\s,;"]+', url)
        primary_url = urls[0] if urls else url
        normalized = normalize_url(primary_url)

        if normalized in seen_urls:
            stats["duplicates"] += 1
            return
        seen_urls.add(normalized)

        owner = extract_owner_from_url(primary_url)
        org_name = org_lookup.get(owner, "")
        company_name = company_lookup.get(owner, "")
        foundation_name = foundation_lookup.get(owner, "")

        output_rows.append({
            "name": row.get("项目名称", ""),
            "url": primary_url,
            "type": "repo",
            "category": row.get("分类", ""),
            "organization": org_name,
            "company": company_name,
            "foundation": foundation_name,
            "stars": row.get("stars", ""),
            "last_active": row.get("pushed_at", ""),
            "description": row.get("description", ""),
            "evidence": row.get("reason", ""),
        })
        stats[source] += 1

    for row in all_repos:
        add_repo(row, "seed_repos")
    for row in org_expanded:
        add_repo(row, "org_expanded")
    for row in foundation_expanded:
        add_repo(row, "foundation_expanded")

    # --- Add organizations ---
    for row in organizations:
        url = row.get("url", "").strip()
        normalized = normalize_url(url) if url else ""
        if normalized and normalized in seen_urls:
            stats["duplicates"] += 1
            continue
        if normalized:
            seen_urls.add(normalized)

        owner = row.get("owner", "").strip().lower()
        output_rows.append({
            "name": row.get("name", row.get("owner", "")),
            "url": url,
            "type": "organization",
            "category": row.get("分类", ""),
            "organization": "",
            "company": company_lookup.get(owner, ""),
            "foundation": foundation_lookup.get(owner, ""),
            "stars": "",
            "last_active": "",
            "description": row.get("description", ""),
            "evidence": row.get("source", ""),
        })
        stats["organizations"] += 1

    # --- Add companies ---
    for row in companies:
        name = row.get("company", "").strip()
        url = row.get("url", "").strip()
        if not name:
            continue
        output_rows.append({
            "name": name,
            "url": url,
            "type": "company",
            "category": "",
            "organization": "",
            "company": "",
            "foundation": "",
            "stars": "",
            "last_active": "",
            "description": "",
            "evidence": row.get("evidence", ""),
        })
        stats["companies"] += 1

    # --- Add foundations ---
    for row in foundations:
        name = row.get("foundation", "").strip()
        url = row.get("url", "").strip()
        if not name:
            continue
        output_rows.append({
            "name": name,
            "url": url,
            "type": "foundation",
            "category": "",
            "organization": "",
            "company": "",
            "foundation": "",
            "stars": "",
            "last_active": "",
            "description": "",
            "evidence": row.get("evidence", ""),
        })
        stats["foundations"] += 1

    # --- Output ---
    out = sys.stdout
    if args.output:
        out = open(args.output, "w", encoding="utf-8", newline="")

    writer = csv.DictWriter(out, fieldnames=OUTPUT_FIELDNAMES)
    writer.writeheader()
    for row in output_rows:
        writer.writerow(row)

    if args.output:
        out.close()

    # --- Summary ---
    if args.summary:
        total = len(output_rows)
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Final Merge Summary (Step ⑧)", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Seed repos:               {stats['seed_repos']}", file=sys.stderr)
        print(f"  Org-expanded repos:       {stats['org_expanded']}", file=sys.stderr)
        print(f"  Foundation-expanded repos: {stats['foundation_expanded']}", file=sys.stderr)
        print(f"  Organizations:            {stats['organizations']}", file=sys.stderr)
        print(f"  Companies:                {stats['companies']}", file=sys.stderr)
        print(f"  Foundations:               {stats['foundations']}", file=sys.stderr)
        print(f"  Duplicates removed:       {stats['duplicates']}", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)
        print(f"  Total in final.csv:       {total}", file=sys.stderr)


if __name__ == "__main__":
    main()
