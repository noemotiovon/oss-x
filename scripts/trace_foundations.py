#!/usr/bin/env python3
"""
Prepare data for foundation tracing (Step ⑤).

Reads all_repos.csv and organizations.csv, extracts unique entities,
applies known-foundation heuristics, and outputs a candidates file for
LLM + human review.

Usage:
  python3 scripts/trace_foundations.py output/all_repos.csv output/organizations.csv \
      -o output/foundations_candidates.csv --summary
"""

import argparse
import csv
import sys
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Known foundations — curated mapping of GitHub org/owner/project → foundation
# ---------------------------------------------------------------------------

KNOWN_FOUNDATIONS = {
    # GitHub org name (lowercase) → foundation name
    "apache": "Apache Software Foundation",
    "cncf": "Cloud Native Computing Foundation (CNCF)",
    "kubernetes": "Cloud Native Computing Foundation (CNCF)",
    "prometheus": "Cloud Native Computing Foundation (CNCF)",
    "envoyproxy": "Cloud Native Computing Foundation (CNCF)",
    "grpc": "Cloud Native Computing Foundation (CNCF)",
    "etcd-io": "Cloud Native Computing Foundation (CNCF)",
    "open-telemetry": "Cloud Native Computing Foundation (CNCF)",
    "argoproj": "Cloud Native Computing Foundation (CNCF)",
    "fluent": "Cloud Native Computing Foundation (CNCF)",
    "containerd": "Cloud Native Computing Foundation (CNCF)",
    "coredns": "Cloud Native Computing Foundation (CNCF)",
    "vitessio": "Cloud Native Computing Foundation (CNCF)",
    "jaegertracing": "Cloud Native Computing Foundation (CNCF)",
    "thanos-io": "Cloud Native Computing Foundation (CNCF)",
    "falcosecurity": "Cloud Native Computing Foundation (CNCF)",
    "cilium": "Cloud Native Computing Foundation (CNCF)",
    "eclipse": "Eclipse Foundation",
    "eclipse-vertx": "Eclipse Foundation",
    "eclipse-theia": "Eclipse Foundation",
    "openstack": "OpenInfra Foundation",
    "starlingx": "OpenInfra Foundation",
    "openinfra": "OpenInfra Foundation",
    "nodejs": "OpenJS Foundation",
    "jquery": "OpenJS Foundation",
    "webpack": "OpenJS Foundation",
    "expressjs": "OpenJS Foundation",
    "electron": "OpenJS Foundation",
    "openjsf": "OpenJS Foundation",
    "python": "Python Software Foundation",
    "pypa": "Python Software Foundation",
    "rust-lang": "Rust Foundation",
    "linuxfoundation": "Linux Foundation",
    "lf-edge": "Linux Foundation (LF Edge)",
    "lfai": "Linux Foundation (LF AI & Data)",
    "hyperledger": "Linux Foundation (Hyperledger)",
    "zephyrproject-rtos": "Linux Foundation (Zephyr)",
    "openssf": "Linux Foundation (OpenSSF)",
    "todogroup": "Linux Foundation (TODO Group)",
    "onnx": "Linux Foundation (LF AI & Data)",
    "pytorch": "Linux Foundation (PyTorch Foundation)",
    "torvalds": "Linux Foundation",
    "freedesktop": "freedesktop.org",
    "gnome": "GNOME Foundation",
    "kde": "KDE e.V.",
    "mozilla": "Mozilla Foundation",
    "wikimedia": "Wikimedia Foundation",
    "w3c": "W3C",
    "oasis-open": "OASIS Open",
}

# Known project → foundation mappings (for repos that don't match org-level)
KNOWN_PROJECT_FOUNDATIONS = {
    "linux": "Linux Foundation",
    "kubernetes": "Cloud Native Computing Foundation (CNCF)",
    "tensorflow": "Linux Foundation",
    "pytorch": "Linux Foundation (PyTorch Foundation)",
    "node": "OpenJS Foundation",
    "chromium": "N/A (Google-led)",
}


def lookup_foundation(owner: str, repo_name: str = "") -> str | None:
    """Try to find a known foundation for a GitHub owner or project."""
    owner_lower = owner.strip().lower()
    if owner_lower in KNOWN_FOUNDATIONS:
        return KNOWN_FOUNDATIONS[owner_lower]

    repo_lower = repo_name.strip().lower()
    if repo_lower in KNOWN_PROJECT_FOUNDATIONS:
        return KNOWN_PROJECT_FOUNDATIONS[repo_lower]

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Prepare foundation tracing candidates (step ⑤)"
    )
    parser.add_argument("repos_csv", help="Path to all_repos.csv")
    parser.add_argument("orgs_csv", help="Path to organizations.csv")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    args = parser.parse_args()

    # --- Read organizations.csv ---
    orgs = []
    with open(args.orgs_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            orgs.append(row)

    # --- Build candidates: one per unique org/owner ---
    fieldnames = [
        "owner", "name", "foundation", "confidence", "source",
        "platform", "url", "description",
        "repo_count", "repos_list",
    ]
    candidates = []
    seen_owners = set()

    for row in orgs:
        owner = row.get("owner", "").strip()
        if not owner or owner.lower() in seen_owners:
            continue
        seen_owners.add(owner.lower())

        foundation = lookup_foundation(owner)
        candidates.append({
            "owner": owner,
            "name": row.get("name", owner),
            "foundation": foundation or "",
            "confidence": "high" if foundation else "unknown",
            "source": "已知基金会映射" if foundation else "待LLM研究",
            "platform": row.get("platform", ""),
            "url": row.get("url", ""),
            "description": row.get("description", ""),
            "repo_count": row.get("repo_count", ""),
            "repos_list": row.get("repos_list", ""),
        })

    # Sort: known foundations first, then unknowns by repo_count desc
    candidates.sort(key=lambda r: (
        0 if r["confidence"] == "high" else 1,
        -int(r["repo_count"]) if r["repo_count"] else 0
    ))

    # --- Output ---
    out = sys.stdout
    if args.output:
        out = open(args.output, "w", encoding="utf-8", newline="")

    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for row in candidates:
        writer.writerow(row)

    if args.output:
        out.close()

    # --- Summary ---
    known = sum(1 for c in candidates if c["confidence"] == "high")
    unknown = len(candidates) - known

    if args.summary:
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Foundation Tracing Candidates (Step ⑤)", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        print(f"  Total unique owners:      {len(candidates)}", file=sys.stderr)
        print(f"  Known foundations:         {known}", file=sys.stderr)
        print(f"  Need LLM research:        {unknown}", file=sys.stderr)

    sys.exit(1 if unknown > 0 else 0)


if __name__ == "__main__":
    main()
