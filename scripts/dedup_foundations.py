#!/usr/bin/env python3
"""
Deduplicate foundations.csv by normalized name (Step ⑦ prep).

Reads foundations.csv, deduplicates by foundation name (case-insensitive),
merges associated orgs/repos, and outputs foundations_deduped.csv.

Usage:
  python3 scripts/dedup_foundations.py output/foundations.csv -o output/foundations_deduped.csv --summary
"""

import argparse
import csv
import sys


def normalize_name(name: str) -> str:
    """Normalize foundation name for dedup."""
    return name.strip().lower()


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate foundations.csv (step ⑦ prep)"
    )
    parser.add_argument("csv_file", help="Path to foundations.csv")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    args = parser.parse_args()

    # --- Read foundations.csv ---
    rows = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            rows.append(row)

    # --- Deduplicate by foundation name ---
    # key: normalized name → merged row
    merged = {}
    for row in rows:
        name = row.get("foundation", "").strip()
        key = normalize_name(name)
        if not key:
            continue

        if key not in merged:
            merged[key] = dict(row)
        else:
            existing = merged[key]
            # Merge associated_orgs
            orgs_existing = set(existing.get("associated_orgs", "").split(";"))
            orgs_new = set(row.get("associated_orgs", "").split(";"))
            existing["associated_orgs"] = ";".join(sorted((orgs_existing | orgs_new) - {""}))
            # Merge associated_repos
            repos_existing = set(existing.get("associated_repos", "").split(";"))
            repos_new = set(row.get("associated_repos", "").split(";"))
            existing["associated_repos"] = ";".join(sorted((repos_existing | repos_new) - {""}))
            # Keep richer evidence
            if len(row.get("evidence", "")) > len(existing.get("evidence", "")):
                existing["evidence"] = row["evidence"]
            # Keep non-empty URL
            if not existing.get("url") and row.get("url"):
                existing["url"] = row["url"]

    deduped = list(merged.values())

    # --- Output ---
    output_fieldnames = fieldnames if fieldnames else [
        "foundation", "url", "associated_orgs", "associated_repos", "evidence"
    ]

    out = sys.stdout
    if args.output:
        out = open(args.output, "w", encoding="utf-8", newline="")

    writer = csv.DictWriter(out, fieldnames=output_fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in deduped:
        writer.writerow(row)

    if args.output:
        out.close()

    if args.summary:
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Foundation Dedup Summary (Step ⑦)", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        print(f"  Input foundations:     {len(rows)}", file=sys.stderr)
        print(f"  After dedup:          {len(deduped)}", file=sys.stderr)
        print(f"  Duplicates merged:    {len(rows) - len(deduped)}", file=sys.stderr)


if __name__ == "__main__":
    main()
