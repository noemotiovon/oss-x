#!/usr/bin/env python3
"""
Trace foundation affiliations for repos.

Strategy (3 layers):
  Layer 1: Match repos against a pre-built foundation project cache
  Layer 2: GitHub org-name heuristics (e.g., "apache/*" → Apache)
  Layer 3: Mark remaining repos for LLM Web Search

The foundation cache is built externally (via LLM Web Search) and stored in
output/.cache/foundation_projects.json.  The script reads it, matches, and
outputs results.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

CACHE_DIR = Path("output/.cache")
FOUNDATION_CACHE = CACHE_DIR / "foundation_projects.json"

# ---------------------------------------------------------------------------
# Built-in org-name → foundation mapping (Layer 2 heuristics)
# ---------------------------------------------------------------------------

ORG_FOUNDATION_MAP = {
    # Apache Software Foundation
    "apache": "Apache Software Foundation",
    # Linux Foundation (umbrella)
    "torvalds": "Linux Foundation",
    "linuxfoundation": "Linux Foundation",
    "lf-edge": "Linux Foundation",
    "lfai": "Linux Foundation",
    "lfnetworking": "Linux Foundation",
    "openssf": "Linux Foundation",
    "todogroup": "Linux Foundation",
    # CNCF (under LF)
    "cncf": "CNCF",
    "kubernetes": "CNCF",
    "kubernetes-sigs": "CNCF",
    "grpc": "CNCF",
    "envoyproxy": "CNCF",
    "etcd-io": "CNCF",
    "containerd": "CNCF",
    "coredns": "CNCF",
    "argoproj": "CNCF",
    "fluxcd": "CNCF",
    "open-telemetry": "CNCF",
    "thanos-io": "CNCF",
    "tikv": "CNCF",
    "vitessio": "CNCF",
    "jaegertracing": "CNCF",
    "linkerd": "CNCF",
    "nats-io": "CNCF",
    "projectcontour": "CNCF",
    "buildpacks": "CNCF",
    "dragonflyoss": "CNCF",
    "falcosecurity": "CNCF",
    "fluent": "CNCF",
    "goharbor": "CNCF",
    "helm": "CNCF",
    "kedacore": "CNCF",
    "kubeedge": "CNCF",
    "kubevirt": "CNCF",
    "longhorn": "CNCF",
    "open-policy-agent": "CNCF",
    "operator-framework": "CNCF",
    "prometheus": "CNCF",
    "rook": "CNCF",
    "spiffe": "CNCF",
    "strimzi": "CNCF",
    # PyTorch Foundation (under LF)
    "pytorch": "PyTorch Foundation",
    # OpenJS Foundation (under LF)
    "nodejs": "OpenJS Foundation",
    "electron": "OpenJS Foundation",
    "jquery": "OpenJS Foundation",
    "webpack": "OpenJS Foundation",
    "expressjs": "OpenJS Foundation",
    "jestjs": "OpenJS Foundation",
    # Eclipse Foundation
    "eclipse": "Eclipse Foundation",
    "eclipse-ee4j": "Eclipse Foundation",
    "eclipse-theia": "Eclipse Foundation",
    "adoptium": "Eclipse Foundation",
    "eclipse-vertx": "Eclipse Foundation",
    "jakartaee": "Eclipse Foundation",
    # OpenInfra Foundation
    "openstack": "OpenInfra Foundation",
    # Python Software Foundation
    "python": "Python Software Foundation",
    "psf": "Python Software Foundation",
    "pypa": "Python Software Foundation",
    # Rust Foundation
    "rust-lang": "Rust Foundation",
    # GNOME Foundation
    "gnome": "GNOME Foundation",
    # KDE
    "kde": "KDE e.V.",
    # Mozilla Foundation
    "mozilla": "Mozilla Foundation",
    # FreeBSD Foundation
    "freebsd": "FreeBSD Foundation",
    # OpenCV
    "opencv": "OpenCV Foundation",
    # Blender Foundation
    "blender": "Blender Foundation",
    # NumFOCUS
    "numpy": "NumFOCUS",
    "pandas-dev": "NumFOCUS",
    "scipy": "NumFOCUS",
    "matplotlib": "NumFOCUS",
    "jupyter": "NumFOCUS",
    "scikit-learn": "NumFOCUS",
    # LLVM Foundation
    "llvm": "LLVM Foundation",
    # .NET Foundation
    "dotnet": ".NET Foundation",
    "dotnet-foundation": ".NET Foundation",
    # Django Software Foundation
    "django": "Django Software Foundation",
    # Linux Foundation (additional projects)
    "dpdk": "Linux Foundation",
    "spdk": "Linux Foundation",
    "o3de": "Linux Foundation",
    "openvswitch": "Linux Foundation",
    "sonic-net": "Linux Foundation",
    "apptainer": "Linux Foundation",
    "jenkinsci": "Linux Foundation",
    # CNCF (additional projects)
    "kubeflow": "CNCF",
    "kserve": "CNCF",
    "fluid-cloudnative": "CNCF",
    # OpenInfra Foundation (additional)
    "kata-containers": "OpenInfra Foundation",
    # LF AI & Data (additional)
    "opea-project": "LF AI & Data",
    # PyTorch Foundation (additional projects)
    "vllm-project": "PyTorch Foundation",
    "ray-project": "PyTorch Foundation",
    "deepspeedai": "PyTorch Foundation",
    # OpenSSL Foundation
    "openssl": "OpenSSL Foundation",
    # Erlang Ecosystem Foundation
    "erlang": "Erlang Ecosystem Foundation",
    # OSGeo Foundation
    "osgeo": "OSGeo Foundation",
    "qgis": "OSGeo Foundation",
    # Software Freedom Conservancy
    "git": "Software Freedom Conservancy",
    # Wireshark Foundation
    "wireshark": "Wireshark Foundation",
    # VideoLAN (non-profit)
    "videolan": "VideoLAN",
    # Apache brpc (old org before move to apache/)
    "brpc": "Apache Software Foundation",
    # Perl & Raku Foundation
    "perl": "Perl & Raku Foundation",
}


def load_foundation_cache():
    """Load the foundation project cache built by LLM."""
    if FOUNDATION_CACHE.exists():
        try:
            with open(FOUNDATION_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_foundation_cache(cache):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FOUNDATION_CACHE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    tmp.replace(FOUNDATION_CACHE)


def extract_github_owner_repo(url):
    """Extract (owner, repo) from GitHub URL."""
    parsed = urlparse((url or "").strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    if host != "github.com":
        return None, None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return parts[0].lower(), parts[1].lower()
    elif len(parts) == 1:
        return parts[0].lower(), None
    return None, None


def match_foundation(owner, repo, project_name, cache):
    """
    Try to match a repo to a foundation.

    Returns (foundation_name, evidence, confidence) or None.
    """
    # Layer 1: Check foundation project cache (project-level match)
    # Cache format: { "Foundation Name": { "projects": ["owner/repo", ...], "evidence": "..." } }
    full_name = f"{owner}/{repo}" if owner and repo else None
    project_lower = (project_name or "").strip().lower()

    for foundation_name, fdata in cache.items():
        projects = fdata.get("projects", [])
        # Match by owner/repo
        if full_name:
            for p in projects:
                if p.lower() == full_name:
                    return (foundation_name, f"基金会项目列表匹配: {p}", "S")
        # Match by project name
        if project_lower:
            for p in projects:
                p_repo = p.split("/")[-1].lower() if "/" in p else p.lower()
                if p_repo == project_lower:
                    return (foundation_name, f"基金会项目名匹配: {p}", "A")

    # Layer 2: GitHub org heuristics
    if owner and owner in ORG_FOUNDATION_MAP:
        foundation = ORG_FOUNDATION_MAP[owner]
        return (foundation, f"GitHub org匹配: {owner} → {foundation}", "S")

    return None


def main():
    parser = argparse.ArgumentParser(description="Trace foundation affiliations")
    parser.add_argument("csv_file", help="Path to repo_exp.csv")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    # Read repos
    rows = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    # Load cache
    cache = load_foundation_cache()
    if cache:
        total_projects = sum(len(v.get("projects", [])) for v in cache.values())
        print(f"Loaded foundation cache: {len(cache)} foundations, {total_projects} projects", file=sys.stderr)
    else:
        print("No foundation cache found. Run LLM step to build it first.", file=sys.stderr)

    # Match
    matched = 0
    unmatched = 0
    output_fields = list(rows[0].keys()) + ["foundation_name", "evidence", "confidence"]

    for row in rows:
        url = row.get("上游地址", "")
        name = row.get("项目名称", "")
        owner, repo = extract_github_owner_repo(url)

        result = match_foundation(owner, repo, name, cache)
        if result:
            row["foundation_name"], row["evidence"], row["confidence"] = result
            matched += 1
        else:
            row["foundation_name"] = "unknown"
            row["evidence"] = ""
            row["confidence"] = ""
            unmatched += 1

    # Write output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in output_fields})

    if args.summary:
        from collections import Counter
        foundations = Counter(r.get("foundation_name", "unknown") for r in rows)
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Foundation Tracing Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Total repos:     {len(rows)}", file=sys.stderr)
        print(f"  Matched:         {matched}", file=sys.stderr)
        print(f"  Unmatched:       {unmatched} (need LLM)", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)
        print(f"  By foundation:", file=sys.stderr)
        for f_name, count in foundations.most_common():
            if f_name != "unknown":
                print(f"    {f_name:40s} {count}", file=sys.stderr)
        print(f"    {'unknown':40s} {foundations.get('unknown', 0)}", file=sys.stderr)


if __name__ == "__main__":
    main()
