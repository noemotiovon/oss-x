#!/usr/bin/env python3
"""
Classify entities from data.csv into: repo, organization, foundation, company.

Principle: script ONLY outputs "repo" or "organization" when 100% certain.
Everything else is marked "unknown" for manual review / LLM fallback.

Certainty rules:
  - repo: URL matches github.com/{owner}/{repo} or gitlab.xxx/{owner}/{repo}
          (exactly 2 path segments, known git hosting platform)
  - organization: URL matches github.com/{owner} (exactly 1 path segment, org-level)
  - unknown: all other cases (website URLs, multi-URL fields, non-git-hosting, etc.)
"""

import argparse
import csv
import json
import os
import re
import sys
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Known git hosting platforms
# ---------------------------------------------------------------------------

GIT_HOSTS = {
    "github.com",
    "gitlab.com",
    "gitlab.freedesktop.org",
    "gitlab.gnome.org",
    "salsa.debian.org",
    "gitee.com",
    "codeberg.org",
    "code.videolan.org",
    "git.kernel.org",
    "git.musl-libc.org",
    "git.whamcloud.com",
    "git.fmrib.ox.ac.uk",
    "svn.oss.deltares.nl",
}

# Patterns: any gitlab.* subdomain is also a git host
GITLAB_PATTERN = re.compile(r"^gitlab\.", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Known entities — curated lists for foundation & company detection
# ---------------------------------------------------------------------------

# Keys are lowercase project names or GitHub org names
KNOWN_FOUNDATIONS = {
    "linux foundation", "cncf", "apache software foundation", "apache",
    "eclipse foundation", "openstack foundation", "openinfra foundation",
    "lfai", "lf edge", "lf networking", "openssf",
    "python software foundation", "psf",
}

# GitHub org names with known parent company/institution.
# Classification step marks these as "organization";
# company tracing (/trace-companies) resolves the parent relationship.
KNOWN_ORG_OWNERS = {
    # GitHub org name → parent company/institution
    "meituan": "美团",
    "deepseek-ai": "DeepSeek",
    "qwenlm": "阿里/通义千问",
    "thudm": "清华大学",
    "inclusionai": "蚂蚁",
    "android": "Google",
}


def is_git_host(hostname: str) -> bool:
    """Check if hostname is a known git hosting platform."""
    if not hostname:
        return False
    hostname = hostname.lower()
    if hostname in GIT_HOSTS:
        return True
    if GITLAB_PATTERN.match(hostname):
        return True
    return False


# ---------------------------------------------------------------------------
# URL parsing & classification
# ---------------------------------------------------------------------------

def extract_urls(raw: str) -> list[str]:
    """Extract all URLs from a field (may contain multiple URLs separated by newlines)."""
    return [u.strip() for u in re.findall(r'https?://[^\s,;"]+', raw)]


def classify_platform_url(host: str, parsed) -> dict | None:
    """
    Classify URLs from known software hosting platforms (not git hosts).
    Returns classification dict or None if not recognizable.
    """
    path = parsed.path.strip("/")

    # SourceForge: sourceforge.net/projects/{name} or sourceforge.net/p/{name}
    if host == "sourceforge.net":
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("projects", "p"):
            return {"category": "repo", "confidence": "high",
                    "evidence": f"sourceforge.net/{parts[0]}/{parts[1]}"}
        return None

    # SourceForge subdomains: {project}.sourceforge.io or {project}.sourceforge.net
    if host.endswith(".sourceforge.io") or host.endswith(".sourceforge.net"):
        project = host.split(".")[0]
        return {"category": "repo", "confidence": "high",
                "evidence": f"{project}.sourceforge (project site)"}

    # Bioconductor: bioconductor.org/packages/.../bioc/html/{Package}.html
    if host == "bioconductor.org" and "/bioc/" in path:
        # Extract package name from path
        parts = path.rstrip("/").split("/")
        pkg = parts[-1].replace(".html", "") if parts else None
        if pkg:
            return {"category": "repo", "confidence": "high",
                    "evidence": f"bioconductor.org package: {pkg}"}
        return None

    # GNU FTP: ftp.gnu.org/gnu/{package}
    if host == "ftp.gnu.org":
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "gnu":
            return {"category": "repo", "confidence": "high",
                    "evidence": f"GNU project: {parts[1]}"}
        return None

    return None


def classify_url(url: str) -> dict | None:
    """
    Classify a single URL. Returns classification dict or None if not classifiable.

    Rules (strict):
      - git_host/{owner}/{repo}[/...]  → repo (we allow trailing paths like /tree/main)
      - git_host/{owner}               → organization
      - anything else                   → None (not classifiable by script)
    """
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if not is_git_host(host):
        # --- Non-git-host platform detection ---
        return classify_platform_url(host, parsed)

    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    if len(path_parts) >= 2:
        owner, repo = path_parts[0], path_parts[1]
        return {
            "category": "repo",
            "confidence": "high",
            "evidence": f"{host}/{owner}/{repo}",
        }
    elif len(path_parts) == 1:
        owner = path_parts[0]
        owner_lower = owner.lower()
        if owner_lower in KNOWN_ORG_OWNERS:
            parent = KNOWN_ORG_OWNERS[owner_lower]
            return {
                "category": "organization",
                "confidence": "high",
                "evidence": f"{host}/{owner} (org-level URL, 已知归属: {parent})",
            }
        return {
            "category": "organization",
            "confidence": "high",
            "evidence": f"{host}/{owner} (org-level URL)",
        }

    return None


def classify_row(name: str, url_field: str) -> dict:
    """
    Classify a CSV row.

    Waterfall strategy:
      1. Known-entity lookup (foundation / company lists)
      2. URL-based classification (git-host URLs)
      3. Unknown → needs LLM fallback
    """
    name_lower = name.lower().strip()

    # --- Step 1: Known foundation check ---
    if name_lower in KNOWN_FOUNDATIONS:
        return {"category": "foundation", "reason": f"脚本分类: 已知基金会"}

    # --- Step 2: Extract URLs ---
    urls = extract_urls(url_field)

    # --- Step 3: URL-based repo/org/company classification ---
    if not urls:
        return {"category": "unknown", "reason": "无URL"}

    best = None
    for url in urls:
        result = classify_url(url)
        if result is None:
            continue
        if result["category"] == "repo":
            return {"category": "repo", "reason": f"脚本分类: {result['evidence']}"}
        if best is None:
            best = result

    if best:
        return {"category": best["category"], "reason": f"脚本分类: {best['evidence']}"}

    # All URLs are non-git-host
    return {"category": "unknown", "reason": f"非git托管平台URL ({', '.join(urls)})"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def write_csv(rows: list[dict], fieldnames: list[str], path: str | None):
    """Write rows to a CSV file or stdout."""
    out = sys.stdout
    if path:
        out = open(path, "w", encoding="utf-8", newline="")
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in fieldnames})
    if path:
        out.close()


def main():
    parser = argparse.ArgumentParser(description="Classify entities from data.csv")
    parser.add_argument("csv_file", help="Path to input CSV file")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--output-dir", help="Output directory for split files (repos.csv, non_repos.csv)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    args = parser.parse_args()

    results = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("项目名称", "").strip()
            url_field = row.get("上游地址", "").strip()
            if not name and not url_field:
                continue

            result = classify_row(name, url_field)
            result["页签"] = row.get("页签", "")
            result["序号"] = row.get("序号", "")
            result["项目名称"] = name
            result["分类"] = row.get("分类", "")
            result["上游地址"] = url_field
            results.append(result)

    has_unknown = any(r["category"] == "unknown" for r in results)

    # Build output rows
    fieldnames = ["页签", "序号", "项目名称", "分类", "上游地址", "entity_type", "reason"]
    output_rows = []
    for r in results:
        output_rows.append({
            "页签": r["页签"],
            "序号": r["序号"],
            "项目名称": r["项目名称"],
            "分类": r["分类"],
            "上游地址": r["上游地址"],
            "entity_type": r["category"],
            "reason": r["reason"],
        })

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        write_csv(output_rows, fieldnames, args.output)

    # Split output: repos.csv and non_repos.csv
    output_dir = args.output_dir
    if not output_dir and args.output:
        output_dir = os.path.dirname(args.output) or "."
    if output_dir:
        repos = [r for r in output_rows if r["entity_type"] == "repo"]
        non_repos = [r for r in output_rows if r["entity_type"] != "repo"]

        write_csv(repos, fieldnames, os.path.join(output_dir, "repos.csv"))
        write_csv(non_repos, fieldnames, os.path.join(output_dir, "non_repos.csv"))
        print(f"Split output: {len(repos)} repos, {len(non_repos)} non-repos", file=sys.stderr)

    if args.summary:
        from collections import Counter
        cats = Counter(r["category"] for r in results)
        total = len(results)
        print(f"\n--- Summary ({total} items) ---", file=sys.stderr)
        for cat, count in cats.most_common():
            print(f"  {cat:15s}: {count:4d} ({count/total*100:.1f}%)", file=sys.stderr)
        if has_unknown:
            unknowns = [(r["项目名称"], r["reason"]) for r in results if r["category"] == "unknown"]
            print(f"\nUnknown items ({len(unknowns)}) — need manual review:", file=sys.stderr)
            for name, evidence in unknowns:
                print(f"  - {name:30s} | {evidence}", file=sys.stderr)

    sys.exit(1 if has_unknown else 0)


if __name__ == "__main__":
    main()
