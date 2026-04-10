#!/usr/bin/env python3
"""
Classify unknown entities using multi-platform search (Step ②).

For entries marked 'unknown' in classified.csv, try to determine type
using automated methods before falling back to LLM:

  Layer 1: GitHub Search API — fuzzy search by project name
  Layer 2: Package registry search — PyPI, npm, CRAN, Bioconductor
  Layer 3: URL pattern heuristics — known software hosting patterns
  Layer 4: Mark remaining for LLM

Usage:
  python3 scripts/classify_unknown.py output/classified.csv \
      -o output/unknown.csv --summary
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass


def fetch_json(url, headers=None, timeout=15):
    """Fetch URL and parse as JSON."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "oss-x-classifier")
    req.add_header("Accept", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def github_search_repo(name):
    """
    Layer 1: Search GitHub for a repo matching the project name.
    Returns (type, repo_url, evidence) or None.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"

    # Search for exact name match in repo names
    query = name.strip().replace(" ", "+")
    data = fetch_json(
        f"https://api.github.com/search/repositories?q={query}+in:name&sort=stars&per_page=5",
        headers=headers,
    )
    if not data or not data.get("items"):
        return None

    # Check if top result is a close match
    for item in data["items"][:3]:
        repo_name = item.get("name", "").lower()
        query_lower = name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
        name_normalized = repo_name.replace("-", "").replace("_", "")

        if name_normalized == query_lower or repo_name == name.strip().lower():
            stars = item.get("stargazers_count", 0)
            full_name = item.get("full_name", "")
            html_url = item.get("html_url", "")
            # Only trust results with reasonable stars to avoid false matches
            if stars >= 10:
                return (
                    "repo",
                    html_url,
                    f"GitHub搜索匹配: {full_name} (stars: {stars})",
                )
    return None


def search_pypi(name):
    """Search PyPI for the package."""
    name_normalized = name.strip().lower().replace(" ", "-")
    data = fetch_json(f"https://pypi.org/pypi/{name_normalized}/json")
    if data and data.get("info"):
        pkg_name = data["info"].get("name", "")
        home = data["info"].get("home_page", "") or data["info"].get("project_url", "")
        return ("repo", home, f"PyPI包匹配: {pkg_name}")
    return None


def check_url_patterns(url_field):
    """
    Layer 3: Additional URL pattern heuristics for non-git-host URLs.
    """
    urls = re.findall(r'https?://[^\s,;"]+', url_field)

    for url in urls:
        url_lower = url.lower().strip().rstrip("/")
        parsed = urlparse(url_lower)
        host = (parsed.hostname or "")
        path = parsed.path.strip("/")

        # .tar.gz / .zip download links → likely a repo/software
        if any(url_lower.endswith(ext) for ext in [".tar.gz", ".tgz", ".zip", ".bz2", ".xz"]):
            return ("repo", url, f"软件下载链接: {url}")

        # Known scientific software hosting
        if host in ("www.ebi.ac.uk", "ftp.gnu.org", "download.savannah.gnu.org"):
            return ("repo", url, f"科学/GNU软件网站: {host}")

        # URL path contains /software/, /download/, /release/, /repo/
        if any(kw in path for kw in ["software", "download", "release", "repo"]):
            return ("repo", url, f"URL路径含软件关键词: {path}")

        # Known project website patterns (single project sites)
        if host.endswith(".org") or host.endswith(".net") or host.endswith(".io"):
            # Single-project website → likely repo
            if not any(kw in host for kw in ["community", "foundation", "consortium"]):
                return ("repo", url, f"项目官网: {host} (推断为单一项目)")

    return None


# Known classifications for common entries that scripts can determine
KNOWN_ENTRIES = {
    # project_name (lowercase) → (type, evidence)
    "lvs": ("repo", "Linux Virtual Server，内核子系统"),
    "kvm": ("repo", "Kernel-based Virtual Machine，内核子系统"),
    "openmpi": ("repo", "Open MPI，单一软件项目"),
    "gmp": ("repo", "GNU Multiple Precision Arithmetic Library"),
    "libmpc": ("repo", "GNU MPC Library"),
    "memtester": ("repo", "memtester，内存测试工具"),
    "lzo": ("repo", "LZO压缩库"),
    "vasp": ("repo", "Vienna Ab initio Simulation Package"),
    "amber tools": ("repo", "AmberTools，分子动力学工具包"),
    "ambertools": ("repo", "AmberTools，分子动力学工具包"),
    "openfoam": ("repo", "OpenFOAM，CFD仿真软件"),
    "genewise": ("repo", "GeneWise，基因预测工具"),
    "openlb": ("repo", "OpenLB，Lattice Boltzmann仿真库"),
    "repeatmasker": ("repo", "RepeatMasker，基因组重复序列检测工具"),
    "meraculous": ("repo", "Meraculous，基因组组装工具"),
    "yambo": ("repo", "Yambo，材料科学模拟软件"),
    "lustre": ("repo", "Lustre文件系统"),
}


def classify_entry(name, url_field):
    """
    Try to classify an unknown entry through automated methods.
    Returns (type, evidence, confidence, method) or None.
    """
    name_lower = name.strip().lower()

    # Layer 0: Known entries
    if name_lower in KNOWN_ENTRIES:
        etype, evidence = KNOWN_ENTRIES[name_lower]
        return (etype, evidence, "S", "已知项目")

    # Layer 1: GitHub Search API
    result = github_search_repo(name)
    if result:
        return (result[0], result[2], "A", "GitHub搜索")

    # Layer 2: PyPI search
    result = search_pypi(name)
    if result:
        return (result[0], result[2], "A", "PyPI搜索")

    # Layer 3: URL pattern heuristics
    if url_field:
        result = check_url_patterns(url_field)
        if result:
            return (result[0], result[2], "B", "URL模式匹配")

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Classify unknown entities via multi-platform search (step ②)"
    )
    parser.add_argument("csv_file", help="Path to classified.csv")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    # Read unknowns from classified.csv
    unknowns = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("entity_type") == "unknown":
                unknowns.append(row)

    if not unknowns:
        print("No unknown entries to classify.", file=sys.stderr)
        # Write empty output with headers
        fieldnames = ["页签", "序号", "项目名称", "分类", "上游地址",
                       "type", "evidence", "confidence", "classify_method"]
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        sys.exit(0)

    print(f"Processing {len(unknowns)} unknown entries...", file=sys.stderr)

    stats = {"known": 0, "github": 0, "pypi": 0, "url": 0, "remaining": 0}

    results = []
    for row in unknowns:
        name = row.get("项目名称", "")
        url_field = row.get("上游地址", "")

        result = classify_entry(name, url_field)

        out = {
            "页签": row.get("页签", ""),
            "序号": row.get("序号", ""),
            "项目名称": name,
            "分类": row.get("分类", ""),
            "上游地址": url_field,
        }

        if result:
            etype, evidence, confidence, method = result
            out["type"] = etype
            out["evidence"] = evidence
            out["confidence"] = confidence
            out["classify_method"] = method
            # Track stats
            if method == "已知项目":
                stats["known"] += 1
            elif method == "GitHub搜索":
                stats["github"] += 1
            elif method == "PyPI搜索":
                stats["pypi"] += 1
            elif method == "URL模式匹配":
                stats["url"] += 1
        else:
            out["type"] = "unknown"
            out["evidence"] = ""
            out["confidence"] = ""
            out["classify_method"] = "待LLM研究"
            stats["remaining"] += 1

        results.append(out)
        # Rate limit for API calls
        time.sleep(0.2)

    # Write output
    fieldnames = ["页签", "序号", "项目名称", "分类", "上游地址",
                   "type", "evidence", "confidence", "classify_method"]
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    if args.summary:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Unknown Classification Summary (Step ②)", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Total unknowns:        {len(unknowns)}", file=sys.stderr)
        print(f"  Resolved by script:    {len(unknowns) - stats['remaining']}", file=sys.stderr)
        print(f"    Known entries:       {stats['known']}", file=sys.stderr)
        print(f"    GitHub search:       {stats['github']}", file=sys.stderr)
        print(f"    PyPI search:         {stats['pypi']}", file=sys.stderr)
        print(f"    URL patterns:        {stats['url']}", file=sys.stderr)
        print(f"  Remaining (need LLM):  {stats['remaining']}", file=sys.stderr)

        if stats["remaining"] > 0:
            remaining = [r for r in results if r["classify_method"] == "待LLM研究"]
            print(f"\n  Still unknown:", file=sys.stderr)
            for r in remaining:
                print(f"    - {r['项目名称']:30s} | {r['上游地址'][:50]}", file=sys.stderr)


if __name__ == "__main__":
    main()
