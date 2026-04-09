#!/usr/bin/env python3
"""
Merge organizations from three sources into a single deduplicated org_exp.csv.

Sources:
  1. organization.csv — entities originally classified as organization
  2. repo_known_org.csv — orgs found via GitHub API (owner_type=organization)
  3. repo_unknown_org.csv — orgs resolved via LLM/human (org_name field)
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from urllib.parse import urlparse


OUTPUT_FIELDS = [
    "org_name",
    "org_url",
    "platform",
    "repo_count",
    "页签",
    "项目名称",
    "分类",
    "上游地址",
    "description",
    "blog",
    "location",
    "public_repos",
    "source",
]


def normalize_url(url):
    """Normalize URL for deduplication."""
    url = (url or "").strip().rstrip("/").lower()
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url


def extract_github_owner(url):
    """Extract GitHub owner from URL."""
    parsed = urlparse(url.strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    if host == "github.com":
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts:
            return parts[0].lower()
    return None


def merge_sets(existing, new_val):
    """Merge semicolon-separated values, deduplicating."""
    existing_set = set(v.strip() for v in existing.split(";") if v.strip()) if existing else set()
    new_set = set(v.strip() for v in new_val.split(";") if v.strip()) if new_val else set()
    merged = existing_set | new_set
    return ";".join(sorted(merged))


def merge_comma_sets(existing, new_val):
    """Merge comma-separated values, deduplicating."""
    existing_set = set(v.strip() for v in existing.split(",") if v.strip()) if existing else set()
    new_set = set(v.strip() for v in new_val.split(",") if v.strip()) if new_val else set()
    merged = existing_set | new_set
    return ",".join(sorted(merged))


def main():
    parser = argparse.ArgumentParser(description="Merge organizations from multiple sources")
    parser.add_argument("organization_csv", help="organization.csv from split-merge")
    parser.add_argument("repo_known_org_csv", help="repo_known_org.csv from resolve-orgs")
    parser.add_argument("repo_unknown_org_csv", help="repo_unknown_org.csv from resolve-unknown-orgs")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    # org_key -> org_record
    # Key is normalized org URL
    orgs = {}
    source_counts = {"organization.csv": 0, "repo_known_org.csv": 0, "repo_unknown_org.csv": 0}
    dup_count = 0

    def add_org(key, org_name, org_url, platform, repo_count, tabs, names, categories, urls,
                description="", blog="", location="", public_repos=0, source_label=""):
        nonlocal dup_count
        if key in orgs:
            # Merge
            dup_count += 1
            rec = orgs[key]
            rec["repo_count"] += repo_count
            rec["页签"] = merge_comma_sets(rec["页签"], tabs)
            rec["项目名称"] = merge_sets(rec["项目名称"], names)
            rec["分类"] = merge_comma_sets(rec["分类"], categories)
            rec["上游地址"] = merge_sets(rec["上游地址"], urls)
            if description and not rec["description"]:
                rec["description"] = description
            if blog and not rec["blog"]:
                rec["blog"] = blog
            if location and not rec["location"]:
                rec["location"] = location
            if public_repos > rec.get("public_repos", 0):
                rec["public_repos"] = public_repos
            rec["source"] = merge_comma_sets(rec["source"], source_label)
        else:
            orgs[key] = {
                "org_name": org_name,
                "org_url": org_url,
                "platform": platform,
                "repo_count": repo_count,
                "页签": tabs,
                "项目名称": names,
                "分类": categories,
                "上游地址": urls,
                "description": description,
                "blog": blog,
                "location": location,
                "public_repos": public_repos,
                "source": source_label,
            }

    # --- Source 1: organization.csv ---
    with open(args.organization_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("上游地址", "").strip().rstrip("/")
            name = row.get("项目名称", "").strip()
            key = normalize_url(url) or name.lower()
            owner = extract_github_owner(url)
            platform = "github.com" if owner else ""
            add_org(
                key=key,
                org_name=owner or name,
                org_url=url,
                platform=platform,
                repo_count=0,  # These are org-level entries, not repo counts
                tabs=row.get("页签", ""),
                names=name,
                categories=row.get("分类", ""),
                urls=url,
                source_label="organization.csv",
            )
            source_counts["organization.csv"] += 1

    # --- Source 2: repo_known_org.csv ---
    with open(args.repo_known_org_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("owner_type") != "organization":
                continue
            owner = row.get("owner", "").strip()
            url = row.get("url", "").strip().rstrip("/")
            key = normalize_url(url) or owner.lower()
            add_org(
                key=key,
                org_name=row.get("name", owner),
                org_url=url,
                platform=row.get("platform", "github.com"),
                repo_count=int(row.get("repo_count", 0)),
                tabs=row.get("页签", ""),
                names=row.get("repos_list", ""),
                categories=row.get("分类", ""),
                urls="",
                description=row.get("description", ""),
                blog=row.get("blog", ""),
                location=row.get("location", ""),
                public_repos=int(row.get("public_repos", 0) or 0),
                source_label="repo_known_org.csv",
            )
            source_counts["repo_known_org.csv"] += 1

    # --- Source 3: repo_unknown_org.csv ---
    # Group by org_name/org_url, aggregate repos
    unknown_orgs = defaultdict(list)
    with open(args.repo_unknown_org_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            org_name = row.get("org_name", "").strip()
            org_url = row.get("org_url", "").strip().rstrip("/")
            if not org_name or "(individual)" in org_name:
                continue  # Skip individual maintainers
            unknown_orgs[(org_name, org_url)].append(row)

    for (org_name, org_url), rows in unknown_orgs.items():
        key = normalize_url(org_url) or org_name.lower()
        tabs = set()
        names = set()
        categories = set()
        for r in rows:
            for t in r.get("页签", "").split(","):
                if t.strip():
                    tabs.add(t.strip())
            for n in r.get("repos_list", "").split(";"):
                if n.strip():
                    names.add(n.strip())
            for c in r.get("分类", "").split(","):
                if c.strip():
                    categories.add(c.strip())

        platform = ""
        if "github.com" in org_url:
            platform = "github.com"
        elif "gitlab" in org_url:
            platform = urlparse(org_url).hostname or ""
        elif "gitee.com" in org_url:
            platform = "gitee.com"

        add_org(
            key=key,
            org_name=org_name,
            org_url=org_url,
            platform=platform,
            repo_count=len(rows),
            tabs=",".join(sorted(tabs)),
            names=";".join(sorted(names)),
            categories=",".join(sorted(categories)),
            urls="",
            source_label="repo_unknown_org.csv",
        )
        source_counts["repo_unknown_org.csv"] += 1

    # --- Write output ---
    output_rows = sorted(orgs.values(), key=lambda r: (-r["repo_count"], r["org_name"]))

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in output_rows:
            writer.writerow({k: row.get(k, "") for k in OUTPUT_FIELDS})

    if args.summary:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Organization Merge Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Total unique organizations: {len(orgs)}", file=sys.stderr)
        print(f"  From organization.csv:      {source_counts['organization.csv']}", file=sys.stderr)
        print(f"  From repo_known_org.csv:    {source_counts['repo_known_org.csv']}", file=sys.stderr)
        print(f"  From repo_unknown_org.csv:  {source_counts['repo_unknown_org.csv']}", file=sys.stderr)
        print(f"  Duplicates merged:          {dup_count}", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)
        print(f"\nTop organizations by repo count:", file=sys.stderr)
        for r in output_rows[:15]:
            print(f"  {r['org_name']:40s} repos={r['repo_count']}", file=sys.stderr)


if __name__ == "__main__":
    main()
