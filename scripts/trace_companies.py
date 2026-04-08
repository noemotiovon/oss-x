#!/usr/bin/env python3
"""
Prepare data for company tracing (Step ④).

Reads all_repos.csv and organizations.csv, extracts unique entities,
applies known-company heuristics, and outputs a candidates file for
LLM + human review.

Known companies are auto-assigned. Unknown entities are flagged for LLM research.

Usage:
  python3 scripts/trace_companies.py output/all_repos.csv output/organizations.csv \
      -o output/companies_candidates.csv --summary
"""

import argparse
import csv
import re
import sys
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Known companies — curated mapping of GitHub org/owner → company
# ---------------------------------------------------------------------------

KNOWN_COMPANIES = {
    # GitHub org name (lowercase) → company name
    "google": "Google",
    "microsoft": "Microsoft",
    "facebook": "Meta",
    "meta": "Meta",
    "facebookresearch": "Meta",
    "apple": "Apple",
    "amazon": "Amazon",
    "aws": "Amazon",
    "nvidia": "NVIDIA",
    "intel": "Intel",
    "ibm": "IBM",
    "redhat": "Red Hat (IBM)",
    "oracle": "Oracle",
    "sap": "SAP",
    "salesforce": "Salesforce",
    "alibaba": "阿里巴巴",
    "aliyun": "阿里巴巴",
    "ant-design": "蚂蚁集团",
    "tencent": "腾讯",
    "tencentyun": "腾讯",
    "baidu": "百度",
    "paddlepaddle": "百度",
    "bytedance": "字节跳动",
    "meituan": "美团",
    "deepseek-ai": "DeepSeek",
    "qwenlm": "阿里巴巴/通义千问",
    "thudm": "清华大学",
    "inclusionai": "华为",
    "huawei": "华为",
    "mindspore": "华为",
    "openmmlab": "商汤科技/上海人工智能实验室",
    "modelscope": "阿里巴巴/达摩院",
    "huggingface": "Hugging Face Inc.",
    "openai": "OpenAI",
    "anthropics": "Anthropic",
    "databricks": "Databricks",
    "elastic": "Elastic",
    "hashicorp": "HashiCorp",
    "docker": "Docker Inc.",
    "vmware": "VMware (Broadcom)",
    "jetbrains": "JetBrains",
    "shopify": "Shopify",
    "uber": "Uber",
    "airbnb": "Airbnb",
    "stripe": "Stripe",
    "cloudflare": "Cloudflare",
    "vercel": "Vercel",
    "supabase": "Supabase",
    "grafana": "Grafana Labs",
    "influxdata": "InfluxData",
    "datadog": "Datadog",
    "confluent": "Confluent",
    "cockroachdb": "Cockroach Labs",
    "pingcap": "PingCAP",
    "tikv": "PingCAP",
    "canonical": "Canonical",
    "suse": "SUSE",
    "rancher": "SUSE/Rancher",
    "gitlab-org": "GitLab",
    "jina-ai": "Jina AI",
    "milvus-io": "Zilliz",
    "qdrant": "Qdrant",
    "weaviate": "Weaviate",
    "ray-project": "Anyscale",
    "unslothai": "Unsloth AI",
    "vllm-project": "vLLM (UC Berkeley)",
    "langchain-ai": "LangChain Inc.",
    "llamaindex": "LlamaIndex",
}

# Companies often found via org description / blog patterns
COMPANY_DOMAIN_HINTS = {
    ".com": True,   # commercial domain
    ".io": True,    # common for startups
    ".ai": True,    # AI companies
    ".dev": True,   # developer companies
}


def normalize_owner(owner: str) -> str:
    """Normalize owner name for lookup."""
    return owner.strip().lower().replace("-", "").replace("_", "")


def lookup_company(owner: str) -> str | None:
    """Try to find a known company for a GitHub owner."""
    owner_lower = owner.strip().lower()
    # Direct match
    if owner_lower in KNOWN_COMPANIES:
        return KNOWN_COMPANIES[owner_lower]
    # Normalized match (without hyphens/underscores)
    normalized = normalize_owner(owner)
    for key, company in KNOWN_COMPANIES.items():
        if normalize_owner(key) == normalized:
            return company
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Prepare company tracing candidates (step ④)"
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

    # --- Read all_repos.csv to get unique owners ---
    repo_owners = set()
    with open(args.repos_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("上游地址", "").strip()
            parsed = urlparse(url)
            if (parsed.hostname or "").lower() == "github.com":
                parts = [p for p in parsed.path.strip("/").split("/") if p]
                if parts:
                    repo_owners.add(parts[0])

    # --- Build candidates: one per unique org/owner ---
    fieldnames = [
        "owner", "name", "company", "confidence", "source",
        "platform", "url", "description", "blog",
        "repo_count", "repos_list",
    ]
    candidates = []
    seen_owners = set()

    for row in orgs:
        owner = row.get("owner", "").strip()
        if not owner or owner.lower() in seen_owners:
            continue
        seen_owners.add(owner.lower())

        company = lookup_company(owner)
        candidates.append({
            "owner": owner,
            "name": row.get("name", owner),
            "company": company or "",
            "confidence": "high" if company else "unknown",
            "source": "已知企业映射" if company else "待LLM研究",
            "platform": row.get("platform", ""),
            "url": row.get("url", ""),
            "description": row.get("description", ""),
            "blog": row.get("blog", ""),
            "repo_count": row.get("repo_count", ""),
            "repos_list": row.get("repos_list", ""),
        })

    # Sort: known companies first, then unknowns by repo_count desc
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
        print(f"Company Tracing Candidates (Step ④)", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        print(f"  Total unique owners:   {len(candidates)}", file=sys.stderr)
        print(f"  Known companies:       {known}", file=sys.stderr)
        print(f"  Need LLM research:     {unknown}", file=sys.stderr)

    sys.exit(1 if unknown > 0 else 0)


if __name__ == "__main__":
    main()
