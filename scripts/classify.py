#!/usr/bin/env python3
"""
Classify each row in data.csv as repo / organization / unknown, based on 上游地址.

Generic rules (platform-agnostic):
  1. No URL                                               → unknown
  2. GitHub:
       github.com/{owner}/{repo}[/...]                    → repo
       github.com/{owner}                                 → API /users/{owner}:
           Organization → organization; User → repo (个人仓库视为 repo 的载体? 否, 单段必是 org/user 根); 这里 User 仍视为 organization-like? 保守处理: Organization→organization, 其他→unknown
  3. Known multi-tenant git-hosting platforms
     (gitlab.*, bitbucket.org, gitee.com, codeberg.org,
      atomgit.com, opendev.org, salsa.debian.org,
      sourceforge.net, framagit.org, git.sr.ht):
       host/{owner}/{repo}[/...]                          → repo
       host/{owner}                                       → organization
       sourceforge.net/projects/{name}                    → repo
       sourceforge.net/p/{name}                           → repo
  4. Single-project git servers / archives (host 本身就代表一个项目或给出具体 repo 路径):
     *.googlesource.com, git.*, svn.*, sourceware.org/git,
     ftp.gnu.org/gnu/{pkg}, *.sourceforge.io/net,
     bioconductor.org/packages/.../{pkg}.html,
     URL 以 .git 结尾                                     → repo
  5. 任意其他 http(s) URL (项目官网等)                    → repo
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

GITHUB_API = "https://api.github.com"

MULTI_TENANT_HOSTS = {
    "bitbucket.org",
    "gitee.com",
    "codeberg.org",
    "atomgit.com",
    "opendev.org",
    "salsa.debian.org",
    "sourceforge.net",
    "framagit.org",
    "git.sr.ht",
    "sr.ht",
}

GITLAB_PATTERN = re.compile(r"^gitlab\.", re.IGNORECASE)


def is_multi_tenant(host: str) -> bool:
    return host in MULTI_TENANT_HOSTS or bool(GITLAB_PATTERN.match(host))


def gh_get(path: str) -> tuple[int, dict | None]:
    token = os.environ.get("GITHUB_TOKEN", "")
    req = urllib.request.Request(f"{GITHUB_API}{path}")
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError):
        return 0, None


URL_RE = re.compile(r"https?://[^\s,;\"'<>]+")


def extract_url(raw: str) -> str | None:
    m = URL_RE.search(raw)
    return m.group(0).rstrip(".,;)") if m else None


def classify(url_field: str) -> tuple[str, str]:
    if not url_field.strip():
        return "unknown", "无URL"

    url = extract_url(url_field)
    if not url:
        return "unknown", f"无法提取URL: {url_field}"

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.strip("/").split("/") if p]

    # GitHub
    if host in ("github.com", "www.github.com"):
        if len(parts) >= 2:
            return "repo", f"github.com/{parts[0]}/{parts[1]}"
        if len(parts) == 1:
            status, data = gh_get(f"/users/{parts[0]}")
            time.sleep(0.05)
            if status == 200 and data and data.get("type") == "Organization":
                return "organization", f"github.com/{parts[0]} (API: Organization)"
            if status == 200 and data and data.get("type") == "User":
                return "organization", f"github.com/{parts[0]} (API: User 个人账号 视作 org 根)"
            return "unknown", f"github.com/{parts[0]} (API status={status})"
        return "unknown", "github.com 无路径"

    # SourceForge specialized
    if host == "sourceforge.net":
        if len(parts) >= 2 and parts[0] in ("projects", "p"):
            return "repo", f"sourceforge.net/{parts[0]}/{parts[1]}"
        if len(parts) == 1:
            return "organization", f"sourceforge.net/{parts[0]}"
    if host.endswith(".sourceforge.io") or host.endswith(".sourceforge.net"):
        return "repo", f"{host} (项目子域名)"

    # Multi-tenant git platforms
    if is_multi_tenant(host):
        if len(parts) >= 2:
            return "repo", f"{host}/{parts[0]}/{parts[1]}"
        if len(parts) == 1:
            return "organization", f"{host}/{parts[0]} (单段路径, 视为组织/用户根)"
        return "unknown", f"{host} 无路径"

    # Single-project / project-specific hosts → repo
    if url.rstrip("/").endswith(".git"):
        return "repo", f".git URL: {url}"
    if host.endswith(".googlesource.com"):
        return "repo", f"{host} (googlesource 项目)"
    if host.startswith("git.") or host.startswith("svn."):
        return "repo", f"{host} (专用 git/svn 服务器)"
    if host == "sourceware.org" and parts and parts[0] == "git":
        return "repo", f"sourceware.org/git/... ({'/'.join(parts[1:2])})"
    if host == "ftp.gnu.org" and len(parts) >= 2 and parts[0] == "gnu":
        return "repo", f"ftp.gnu.org/gnu/{parts[1]}"
    if host == "bioconductor.org" and "packages" in parts:
        return "repo", f"bioconductor.org package"

    # Generic fallback: any other URL points to a concrete project page
    return "repo", f"项目官网/其他URL: {host}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_file")
    ap.add_argument("-o", "--output", default="output/data_classify.csv")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    fieldnames = list(rows[0].keys()) if rows else []
    for col in ("entity_type", "reason"):
        if col not in fieldnames:
            fieldnames.append(col)

    out_rows = []
    for i, row in enumerate(rows, 1):
        url_field = row.get("上游地址", "").strip()
        entity_type, reason = classify(url_field)
        new_row = dict(row)
        new_row["entity_type"] = entity_type
        new_row["reason"] = reason
        out_rows.append(new_row)
        if args.summary:
            print(f"[{i}/{len(rows)}] {row.get('项目名称','')}: {entity_type}", file=sys.stderr)

    with open(args.output, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    if args.summary:
        from collections import Counter
        c = Counter(r["entity_type"] for r in out_rows)
        print(f"\n--- Summary ({len(out_rows)} rows) → {args.output} ---", file=sys.stderr)
        for k, v in c.most_common():
            print(f"  {k:15s}: {v}", file=sys.stderr)


if __name__ == "__main__":
    main()
