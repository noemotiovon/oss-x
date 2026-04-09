#!/usr/bin/env python3
"""
Split & Merge: combine classified.csv and unknown.csv, then split by type
into repo.csv and organization.csv. Deduplicates by 上游地址.
"""

import argparse
import csv
import os
import sys


OUTPUT_FIELDS = ["页签", "序号", "项目名称", "分类", "上游地址", "entity_type", "reason"]


def read_csv(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize: unknown.csv uses "type"/"evidence", classified.csv uses "entity_type"/"reason"
            entity_type = row.get("entity_type") or row.get("type", "unknown")
            reason = row.get("reason") or row.get("evidence", "")
            rows.append({
                "页签": row.get("页签", ""),
                "序号": row.get("序号", ""),
                "项目名称": row.get("项目名称", ""),
                "分类": row.get("分类", ""),
                "上游地址": row.get("上游地址", ""),
                "entity_type": entity_type,
                "reason": reason,
            })
    return rows


def write_csv(rows, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in OUTPUT_FIELDS})


def main():
    parser = argparse.ArgumentParser(description="Split & merge classified + unknown into repo.csv and organization.csv")
    parser.add_argument("classified", help="Path to classified.csv")
    parser.add_argument("unknown", nargs="?", help="Path to unknown.csv (optional)")
    parser.add_argument("-o", "--output-dir", default="output", help="Output directory")
    args = parser.parse_args()

    all_rows = read_csv(args.classified)
    if args.unknown and os.path.exists(args.unknown):
        unknown_rows = read_csv(args.unknown)
        # Replace unknown entries in classified with resolved ones from unknown.csv
        unknown_keys = {(r["页签"], r["序号"]) for r in unknown_rows}
        all_rows = [r for r in all_rows if (r["页签"], r["序号"]) not in unknown_keys]
        all_rows.extend(unknown_rows)

    # Deduplicate by 上游地址 (keep first occurrence)
    seen = set()
    deduped = []
    dup_count = 0
    for r in all_rows:
        url = r["上游地址"].strip()
        if url and url in seen:
            dup_count += 1
            continue
        if url:
            seen.add(url)
        deduped.append(r)

    repos = [r for r in deduped if r["entity_type"] == "repo"]
    orgs = [r for r in deduped if r["entity_type"] == "organization"]

    os.makedirs(args.output_dir, exist_ok=True)
    repo_path = os.path.join(args.output_dir, "repo.csv")
    org_path = os.path.join(args.output_dir, "organization.csv")

    write_csv(repos, repo_path)
    write_csv(orgs, org_path)

    print(f"repo.csv: {len(repos)} entries", file=sys.stderr)
    print(f"organization.csv: {len(orgs)} entries", file=sys.stderr)
    if dup_count:
        print(f"Duplicates removed: {dup_count}", file=sys.stderr)
    print(f"Total processed: {len(deduped)} (from {len(all_rows) + dup_count - dup_count})", file=sys.stderr)


if __name__ == "__main__":
    main()
