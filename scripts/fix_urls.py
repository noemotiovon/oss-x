#!/usr/bin/env python3
"""
URL fix & resolution (Step 0b).

Reads cleaned.csv, extracts entries that need URL correction:
  1. not_found  — GitHub URL returns 404 (typo, .git suffix, moved)
  2. no_url     — no valid URL provided
  3. potential_mirror — GitHub repo is likely a read-only mirror
     (has_issues=False AND total_pull_requests < 100);
     need to find the REAL upstream (e.g., gitlab, sourceware, kernel.org)

NOTE: non_github entries are NOT included — their URLs are already the
real upstream (bioconductor, gitlab, sourceforge, etc.).

Layers (script-first, LLM-last):
  L0 — Known mappings: static dict of well-known projects
  L1 — URL fix & retry: strip .git suffix, try GitHub API again
  L2 — GitHub Search API: fuzzy search by project name (for not_found/no_url)
  L3 — Mirror detection: fetch repo description/homepage from GitHub API,
       confirm mirror status and extract real upstream URL

Usage:
  python3 scripts/fix_urls.py output/cleaned.csv -o output/fix_urls.csv --summary

Requirements:
  - GITHUB_TOKEN env var
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

CACHE_DIR = Path("output/.cache")
CACHE_FILE = CACHE_DIR / "github_fix_cache.json"

_rate_remaining = None
_rate_reset = None


def _interruptible_wait(seconds: int, label: str = "Rate limit") -> None:
    end_time = time.time() + seconds
    while True:
        remaining = int(end_time - time.time())
        if remaining <= 0:
            break
        print(f"\r  ⏳ {label}: {remaining}s (Ctrl-C to abort)  ",
              end="", file=sys.stderr, flush=True)
        time.sleep(min(5, remaining))
    print(f"\r  ✓ {label} done.{' ' * 40}", file=sys.stderr)


def github_api(endpoint: str) -> dict | list | None:
    global _rate_remaining, _rate_reset
    url = f"https://api.github.com{endpoint}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oss-x-fix-urls",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    if _rate_remaining is not None and _rate_remaining <= 1 and _rate_reset:
        wait = _rate_reset - int(time.time()) + 1
        if wait > 0:
            _interruptible_wait(wait)

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            _rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
            _rate_reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            return json.loads(resp.read().decode())
    except HTTPError as e:
        if e.code == 403:
            reset = e.headers.get("X-RateLimit-Reset")
            if reset:
                wait = int(reset) - int(time.time()) + 1
                if wait > 0:
                    _interruptible_wait(wait, "403 retry")
                    return github_api(endpoint)
        return None
    except (URLError, OSError):
        return None


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    tmp.replace(CACHE_FILE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Normalize project name: lowercase, strip company annotations."""
    n = name.lower().strip()
    n = re.sub(r'[（(][^)）]*[)）]', '', n).strip()
    return n


def _make_result(url: str, evidence: str, confidence: str, layer: str) -> dict:
    return {
        "resolved_url": url,
        "evidence": evidence,
        "confidence": confidence,
        "resolved_by": layer,
    }


# ---------------------------------------------------------------------------
# Layer 0 — Known mappings
# ---------------------------------------------------------------------------

# For not_found / no_url: project_name → correct URL
KNOWN_NOT_FOUND = {
    "suricata": ("https://github.com/OISF/suricata",
                 ".git suffix caused 404"),
    "mesa": ("https://gitlab.freedesktop.org/mesa/mesa",
             "official upstream is on freedesktop GitLab"),
    "3fs": ("https://github.com/deepseek-ai/3FS",
            "repo is under deepseek-ai, not 3fs org"),
    "juicefs": ("https://github.com/juicedata/juicefs",
                "repo is under juicedata, not juicefs org"),
    "mooncake": ("https://github.com/kvcache-ai/Mooncake",
                 "repo is under kvcache-ai, not mooncake-ai"),
    "openvelinux": ("https://github.com/openvelinux",
                    "is an org (openvelinux), not a single repo"),
    "opencloudos": ("https://github.com/OpenCloudOS",
                    "is an org, not a single repo named OpenCloudOS"),
    "cloudwego": ("https://github.com/cloudwego",
                  "is an org (kitex/hertz/etc), not a single repo"),
    "vvenc": ("https://github.com/fraunhoferhhi/vvenc",
              "repo is under fraunhoferhhi, not ultravideo"),
    "xla": ("https://github.com/openxla/xla",
            "moved from tensorflow/xla to openxla/xla"),
    "scann": ("https://github.com/google-research/google-research/tree/master/scann",
              "ScaNN is a subdirectory inside google-research, not a standalone repo"),
    "rabitq": ("https://github.com/gaoj0017/RaBitQ",
               "correct case is RaBitQ under gaoj0017"),
    "sonic-cpp": ("https://github.com/bytedance/sonic-cpp",
                  "repo is under bytedance, not sonic-net"),
    "lvs": ("https://github.com/alibaba/LVS",
            "LVS is kernel-integrated; alibaba/LVS is the main open-source fork"),
}

# For potential_mirror: project_name → real upstream URL
KNOWN_MIRRORS = {
    "glibc": ("https://sourceware.org/git/glibc.git",
              "official upstream is sourceware.org"),
    "ffmpeg": ("https://git.ffmpeg.org/ffmpeg.git",
               "official upstream is git.ffmpeg.org"),
    "qemu": ("https://gitlab.com/qemu-project/qemu",
             "official upstream is QEMU GitLab"),
    "chromium": ("https://chromium.googlesource.com/chromium/src",
                 "official upstream is Chromium Googlesource"),
    "postgresql": ("https://git.postgresql.org/gitweb/?p=postgresql.git",
                   "official upstream is git.postgresql.org"),
    "sqlite": ("https://www.sqlite.org/src",
               "official upstream is sqlite.org Fossil"),
    "cmake": ("https://gitlab.kitware.com/cmake/cmake",
              "official upstream is Kitware GitLab"),
    "lua": ("https://www.lua.org/source/",
            "official upstream is lua.org"),
    "r": ("https://svn.r-project.org/R/",
          "official upstream is R project SVN"),
    "wireshark": ("https://gitlab.com/wireshark/wireshark",
                  "official upstream is Wireshark GitLab"),
    "gromacs": ("https://gitlab.com/gromacs/gromacs",
                "official upstream is GROMACS GitLab"),
    "geant4": ("https://gitlab.cern.ch/geant4/geant4",
               "official upstream is CERN GitLab"),
    "x265": ("https://bitbucket.org/multicoreware/x265_git",
             "official upstream is MulticoreWare Bitbucket"),
    "impala": ("https://github.com/apache/impala",
               "Apache official mirror, dev on Apache infra"),
    "oozie": ("https://github.com/apache/oozie",
              "Apache official mirror, archived"),
    "pig": ("https://github.com/apache/pig",
            "Apache official mirror, dev on Apache infra"),
    "kudu": ("https://github.com/apache/kudu",
             "Apache official mirror, dev on Apache infra"),
    "openstack": ("https://opendev.org/openstack",
                  "official upstream is OpenDev"),
    "apr-util": ("https://github.com/apache/apr-util",
                 "Apache official mirror"),
    "apr": ("https://github.com/apache/apr",
            "Apache official mirror"),
    "libxml2": ("https://gitlab.gnome.org/GNOME/libxml2",
                "official upstream is GNOME GitLab"),
    "quantumespresso": ("https://gitlab.com/QEF/q-e",
                        "official upstream is QEF GitLab"),
    "tophat2": ("https://ccb.jhu.edu/software/tophat/",
                "official site is JHU CCB, repo is unmaintained"),
    "openmolcas": ("https://gitlab.com/Molcas/OpenMolcas",
                   "official upstream is Molcas GitLab"),
    "petsc": ("https://gitlab.com/petsc/petsc",
              "official upstream is PETSc GitLab"),
}


def layer0_known(row: dict) -> dict | None:
    reason = row.get("_reason", "")
    name = _normalize_name(row.get("项目名称", ""))

    if reason in ("not_found", "no_url") and name in KNOWN_NOT_FOUND:
        url, evidence = KNOWN_NOT_FOUND[name]
        return _make_result(url, evidence, "S", "L0-known")

    if reason == "potential_mirror" and name in KNOWN_MIRRORS:
        url, evidence = KNOWN_MIRRORS[name]
        return _make_result(url, evidence, "S", "L0-known")

    return None


# ---------------------------------------------------------------------------
# Layer 1 — URL fix & retry (for not_found only)
# ---------------------------------------------------------------------------

def layer1_url_fix(row: dict, cache: dict) -> dict | None:
    """Strip .git suffix and retry GitHub API."""
    if row.get("_reason") != "not_found":
        return None

    url_field = row.get("上游地址", "").strip()
    urls = re.findall(r'https?://[^\s,;"]+', url_field)

    for u in urls:
        u = u.strip().rstrip("/")
        # Try stripping .git suffix
        candidate = u[:-4] if u.endswith(".git") else None
        if not candidate:
            continue

        parsed = urlparse(candidate)
        if (parsed.hostname or "").lower() != "github.com":
            continue
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) < 2:
            continue
        owner, repo = parts[0], parts[1]

        cache_key = f"fix:{owner}/{repo}"
        if cache_key in cache:
            return cache[cache_key] if cache[cache_key] else None

        data = github_api(f"/repos/{owner}/{repo}")
        if data and data.get("full_name"):
            full_name = data["full_name"]
            result = _make_result(
                f"https://github.com/{full_name}",
                f"stripped .git suffix → valid repo",
                "S", "L1-url_fix",
            )
            cache[cache_key] = result
            _save_cache(cache)
            return result
        cache[cache_key] = None
        _save_cache(cache)

    return None


# ---------------------------------------------------------------------------
# Layer 2 — GitHub Search API (for not_found / no_url only)
# ---------------------------------------------------------------------------

def layer2_github_search(row: dict, cache: dict) -> dict | None:
    """Search GitHub repos by project name."""
    if row.get("_reason") not in ("not_found", "no_url"):
        return None

    name = _normalize_name(row.get("项目名称", ""))
    if not name or len(name) < 2:
        return None

    cache_key = f"search:{name}"
    if cache_key in cache:
        return cache[cache_key]

    print(f"  [L2] GitHub Search: {name}", file=sys.stderr)
    data = github_api(f"/search/repositories?q={quote(name)}&per_page=5&sort=stars")
    if not data or not data.get("items"):
        cache[cache_key] = None
        _save_cache(cache)
        return None

    for item in data["items"]:
        repo_name = item.get("name", "").lower()
        full_name = item.get("full_name", "")
        stars = item.get("stargazers_count", 0)

        if repo_name == name and stars >= 10:
            result = _make_result(
                f"https://github.com/{full_name}",
                f"GitHub Search: '{full_name}' ({stars} stars)",
                "A", "L2-search",
            )
            cache[cache_key] = result
            _save_cache(cache)
            return result

        if name in repo_name and stars >= 100:
            result = _make_result(
                f"https://github.com/{full_name}",
                f"GitHub Search: close match '{full_name}' ({stars} stars)",
                "B", "L2-search",
            )
            cache[cache_key] = result
            _save_cache(cache)
            return result

    cache[cache_key] = None
    _save_cache(cache)
    return None


# ---------------------------------------------------------------------------
# Layer 3 — Mirror detection (for potential_mirror only)
# ---------------------------------------------------------------------------

_MIRROR_KEYWORDS = [
    "mirror", "read-only", "readonly", "unofficial",
    "镜像", "只读",
]

_UPSTREAM_DOMAINS = [
    "gitlab.", "gitee.", "sourceware.org", "git.kernel.org",
    "git.savannah.", "git.sv.gnu.org", "googlesource.com",
    "hg.mozilla.org", "svn.", "ftp.gnu.org", "opendev.org",
    "bitbucket.org", "git.code.sf.net",
]


def layer3_mirror_detect(row: dict, cache: dict) -> dict | None:
    """
    For potential_mirror entries, fetch repo description/homepage from
    GitHub API to determine if it is a mirror and find the real upstream.
    """
    if row.get("_reason") != "potential_mirror":
        return None

    url_field = row.get("上游地址", "").strip()
    effective_url = row.get("actual_url", "").strip() or url_field
    # Strip anything after the repo path (e.g., parenthetical notes)
    effective_url = re.sub(r'\s.*$', '', effective_url)

    parsed = urlparse(effective_url)
    if (parsed.hostname or "").lower() != "github.com":
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]

    cache_key = f"mirror:{owner}/{repo}"
    if cache_key in cache:
        return cache[cache_key]

    print(f"  [L3] Mirror check: {owner}/{repo}", file=sys.stderr)
    data = github_api(f"/repos/{owner}/{repo}")
    if not data:
        cache[cache_key] = None
        _save_cache(cache)
        return None

    description = (data.get("description") or "").lower()
    homepage = data.get("homepage") or ""
    mirror_url = data.get("mirror_url") or ""
    is_fork = data.get("fork", False)

    desc_is_mirror = any(kw in description for kw in _MIRROR_KEYWORDS)
    has_mirror_url = bool(mirror_url)
    homepage_is_upstream = any(d in homepage.lower() for d in _UPSTREAM_DOMAINS)

    # Case 1: GitHub API explicitly knows it's a mirror
    if has_mirror_url:
        result = _make_result(
            mirror_url,
            f"GitHub mirror_url field: '{mirror_url}'",
            "S", "L3-mirror",
        )
        cache[cache_key] = result
        _save_cache(cache)
        return result

    # Case 2: description says "mirror"
    if desc_is_mirror:
        upstream = homepage if homepage_is_upstream else ""
        result = _make_result(
            upstream or "mirror confirmed, upstream unknown",
            f"description: '{data.get('description', '')}', homepage: '{homepage}'",
            "S" if upstream else "B",
            "L3-mirror",
        )
        cache[cache_key] = result
        _save_cache(cache)
        return result

    # Case 3: homepage points to non-GitHub upstream
    if homepage_is_upstream:
        result = _make_result(
            homepage,
            f"homepage points to upstream: '{homepage}'",
            "A", "L3-mirror",
        )
        cache[cache_key] = result
        _save_cache(cache)
        return result

    # Case 4: is a GitHub fork — find parent
    if is_fork:
        parent = data.get("parent", {})
        if parent:
            result = _make_result(
                f"https://github.com/{parent.get('full_name', '')}",
                f"GitHub fork of {parent.get('full_name', '')}",
                "S", "L3-mirror",
            )
            cache[cache_key] = result
            _save_cache(cache)
            return result

    # Not confirmed as mirror
    result = _make_result(
        "",
        f"not confirmed as mirror: desc='{data.get('description', '')}', homepage='{homepage}'",
        "S", "L3-not_mirror",
    )
    cache[cache_key] = result
    _save_cache(cache)
    return result


# ---------------------------------------------------------------------------
# Filtering logic
# ---------------------------------------------------------------------------

def _is_potential_mirror(row: dict) -> bool:
    if row.get("status") != "valid" or row.get("url_type") != "repo":
        return False
    has_issues = row.get("has_issues", "").strip()
    if has_issues not in ("False", "false", "0"):
        return False
    try:
        total_prs = int(row.get("total_pull_requests", "0") or "0")
    except ValueError:
        return False
    return total_prs < 100


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fix problematic URLs from cleaned.csv using multi-layer resolution")
    parser.add_argument("csv_file", help="Path to cleaned.csv")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    args = parser.parse_args()

    if not GITHUB_TOKEN:
        print("Warning: GITHUB_TOKEN not set", file=sys.stderr)

    cache = _load_cache()

    # Read input
    rows = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Filter: only not_found, no_url, potential_mirror
    # non_github entries are EXCLUDED — their URLs are already real upstream
    problematic = []
    for row in rows:
        status = row.get("status", "").strip()
        reason = None
        if status == "not_found":
            reason = "not_found"
        elif status == "no_url":
            reason = "no_url"
        elif _is_potential_mirror(row):
            reason = "potential_mirror"
        if reason:
            row["_reason"] = reason
            problematic.append(row)

    print(f"Found {len(problematic)} entries to fix "
          f"(non_github excluded — already real upstream)\n", file=sys.stderr)

    # Apply resolution layers
    layers = [
        ("L0-known",   layer0_known),
        ("L1-url_fix", lambda r: layer1_url_fix(r, cache)),
        ("L2-search",  lambda r: layer2_github_search(r, cache)),
        ("L3-mirror",  lambda r: layer3_mirror_detect(r, cache)),
    ]

    stats = {name: 0 for name, _ in layers}
    stats["unresolved"] = 0

    out_fields = [
        "页签", "序号", "项目名称", "分类", "上游地址",
        "status", "url_type", "actual_url",
        "reason", "resolved_by", "resolved_url", "evidence", "confidence",
    ]

    out_rows = []
    for i, row in enumerate(problematic):
        reason = row["_reason"]
        result = None

        for layer_name, layer_fn in layers:
            result = layer_fn(row)
            if result:
                stats[layer_name] += 1
                break

        if not result:
            stats["unresolved"] += 1
            result = {"resolved_url": "", "evidence": "", "confidence": "", "resolved_by": ""}

        out_row = {k: row.get(k, "") for k in out_fields[:8]}
        out_row["reason"] = reason
        out_row["resolved_by"] = result.get("resolved_by", "")
        out_row["resolved_url"] = result.get("resolved_url", "")
        out_row["evidence"] = result.get("evidence", "")
        out_row["confidence"] = result.get("confidence", "")
        out_rows.append(out_row)

        if (i + 1) % 20 == 0:
            print(f"  Progress: {i + 1}/{len(problematic)}", file=sys.stderr)

    # Write output
    out = sys.stdout
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        out = open(args.output, "w", encoding="utf-8", newline="")

    writer = csv.DictWriter(out, fieldnames=out_fields)
    writer.writeheader()
    for r in out_rows:
        writer.writerow(r)

    if args.output:
        out.close()
        print(f"\nOutput written to {args.output}", file=sys.stderr)

    # Summary
    if args.summary:
        total = len(out_rows)
        resolved = total - stats["unresolved"]
        from collections import Counter
        reason_counts = Counter(r["reason"] for r in out_rows)
        conf_counts = Counter(r["confidence"] for r in out_rows if r["confidence"])

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Fix URLs Summary ({total} entries)", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        print(f"\nBy category:", file=sys.stderr)
        for reason, count in reason_counts.most_common():
            print(f"  {reason:20s}: {count}", file=sys.stderr)

        print(f"\nResolution by layer:", file=sys.stderr)
        for layer_name, _ in layers:
            count = stats[layer_name]
            if count:
                print(f"  {layer_name:20s}: {count}", file=sys.stderr)
        print(f"  {'unresolved':20s}: {stats['unresolved']}", file=sys.stderr)

        print(f"\nTotal resolved: {resolved}/{total} ({resolved/total*100:.0f}%)", file=sys.stderr)
        print(f"Remaining for LLM: {stats['unresolved']}", file=sys.stderr)

        if conf_counts:
            print(f"\nConfidence distribution:", file=sys.stderr)
            for c in ["S", "A", "B", "C"]:
                if c in conf_counts:
                    print(f"  {c}: {conf_counts[c]}", file=sys.stderr)

        # List unresolved
        unresolved = [r for r in out_rows if not r["resolved_url"] and r["resolved_by"] != "L3-not_mirror"]
        if unresolved:
            print(f"\n⚠ Unresolved ({len(unresolved)}) — need LLM Web Search:", file=sys.stderr)
            for r in unresolved:
                print(f"  - [{r['reason']}] {r['项目名称']:30s} | {r['上游地址']}", file=sys.stderr)

        # List confirmed non-mirrors (potential_mirror that turned out to be real)
        not_mirrors = [r for r in out_rows if r["resolved_by"] == "L3-not_mirror"]
        if not_mirrors:
            print(f"\n✓ Confirmed as real upstream ({len(not_mirrors)}):", file=sys.stderr)
            for r in not_mirrors:
                print(f"  - {r['项目名称']:30s} | {r['上游地址']}", file=sys.stderr)


if __name__ == "__main__":
    main()
