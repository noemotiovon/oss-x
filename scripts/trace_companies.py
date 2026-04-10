#!/usr/bin/env python3
"""
Trace company affiliations for repos (Step ⑩).

3-layer strategy:
  Layer 1: Known company mapping (static dict, highest confidence)
  Layer 2: GitHub API org profile (company/blog/description fields)
  Layer 3: Mark remaining repos for LLM Web Search

Usage:
  python3 scripts/trace_companies.py output/repo_exp.csv \
      -o output/company.csv --summary
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Cache for GitHub API org profile results
# ---------------------------------------------------------------------------

CACHE_DIR = Path("output/.cache")
ORG_PROFILE_CACHE_FILE = CACHE_DIR / "org_profile_cache.json"


def _load_org_cache():
    if ORG_PROFILE_CACHE_FILE.exists():
        try:
            with open(ORG_PROFILE_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"Loaded org profile cache: {len(data)} entries", file=sys.stderr)
            return data
        except Exception:
            pass
    return {}


def _save_org_cache(cache):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ORG_PROFILE_CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    tmp.replace(ORG_PROFILE_CACHE_FILE)

# ---------------------------------------------------------------------------
# Layer 1: Known company mapping (GitHub org → company)
# ---------------------------------------------------------------------------

KNOWN_COMPANIES = {
    # US big tech
    "google": "Google",
    "googlecloudplatform": "Google",
    "googleapis": "Google",
    "googlechrome": "Google",
    "angular": "Google",
    "bazelbuild": "Google",
    "tensorflow": "Google",
    "google-deepmind": "Google DeepMind",
    "deepmind": "Google DeepMind",
    "microsoft": "Microsoft",
    "azure": "Microsoft",
    "dotnet": "Microsoft",
    "facebook": "Meta",
    "meta": "Meta",
    "facebookresearch": "Meta",
    "facebookincubator": "Meta",
    "apple": "Apple",
    "amazon": "Amazon",
    "aws": "Amazon",
    "amzn": "Amazon",
    "nvidia": "NVIDIA",
    "nvidia-ai-iot": "NVIDIA",
    "nvidiaGameworks": "NVIDIA",
    "intel": "Intel",
    "oneapi-src": "Intel",
    "ibm": "IBM",
    "redhat": "Red Hat (IBM)",
    "oracle": "Oracle",
    "sap": "SAP",
    "salesforce": "Salesforce",
    "twitter": "X (Twitter)",
    "x": "X (Twitter)",
    "linkedin": "LinkedIn (Microsoft)",
    "netflix": "Netflix",
    "spotify": "Spotify",
    "pinterest": "Pinterest",
    "snap-inc": "Snap Inc.",
    "sony": "Sony",
    "samsung": "Samsung",
    # AI companies
    "openai": "OpenAI",
    "anthropics": "Anthropic",
    "anthropic-ai": "Anthropic",
    "huggingface": "Hugging Face",
    "mistralai": "Mistral AI",
    "stability-ai": "Stability AI",
    "cohere-ai": "Cohere",
    # Chinese tech
    "alibaba": "阿里巴巴",
    "aliyun": "阿里巴巴",
    "alipay": "蚂蚁集团(阿里巴巴)",
    "ant-design": "蚂蚁集团(阿里巴巴)",
    "ant-financial": "蚂蚁集团(阿里巴巴)",
    "modelscope": "阿里巴巴/达摩院",
    "qwenlm": "阿里巴巴/通义千问",
    "tencent": "腾讯",
    "tencentyun": "腾讯",
    "tencentmusic": "腾讯",
    "wechat-miniprogram": "腾讯",
    "baidu": "百度",
    "paddlepaddle": "百度",
    "bytedance": "字节跳动",
    "deepseek-ai": "DeepSeek(幻方量化)",
    "meituan": "美团",
    "didi": "滴滴",
    "xiaomi": "小米",
    "oppo": "OPPO",
    "vivo-ai-lab": "vivo",
    "huawei": "华为",
    "mindspore": "华为",
    "inclusionai": "华为",
    "openeuler": "华为",
    "opengauss": "华为",
    "openlookeng": "华为",
    "jd-opensource": "京东",
    "pdd-open": "拼多多",
    "netease": "网易",
    "zhihu": "知乎",
    "bilibili": "哔哩哔哩",
    "kuaishou": "快手",
    # Cloud / Infra companies
    "databricks": "Databricks",
    "elastic": "Elastic",
    "hashicorp": "HashiCorp",
    "docker": "Docker Inc.",
    "vmware": "VMware (Broadcom)",
    "vmware-tanzu": "VMware (Broadcom)",
    "confluent": "Confluent",
    "cockroachdb": "Cockroach Labs",
    "pingcap": "PingCAP",
    "tikv": "PingCAP",
    "yugabyte": "YugabyteDB",
    "timescale": "Timescale",
    "clickhouse": "ClickHouse Inc.",
    "starburstdata": "Starburst",
    "firebolt-analytics": "Firebolt",
    "snowflakedb": "Snowflake",
    "vercel": "Vercel",
    "supabase": "Supabase",
    "cloudflare": "Cloudflare",
    "grafana": "Grafana Labs",
    "influxdata": "InfluxData",
    "datadog": "Datadog",
    "newrelic": "New Relic",
    "splunk": "Splunk (Cisco)",
    "sentry-io": "Sentry",
    "canonical": "Canonical",
    "suse": "SUSE",
    "rancher": "SUSE/Rancher",
    "gitlab-org": "GitLab",
    "atlassian": "Atlassian",
    "jetbrains": "JetBrains",
    # Developer tools / Startups
    "shopify": "Shopify",
    "uber": "Uber",
    "airbnb": "Airbnb",
    "stripe": "Stripe",
    "twilio": "Twilio",
    "auth0": "Auth0 (Okta)",
    "okta": "Okta",
    "palantir": "Palantir",
    "snowplow": "Snowplow",
    "jina-ai": "Jina AI",
    "milvus-io": "Zilliz",
    "qdrant": "Qdrant",
    "weaviate": "Weaviate",
    "ray-project": "Anyscale",
    "unslothai": "Unsloth AI",
    "langchain-ai": "LangChain Inc.",
    "llamaindex": "LlamaIndex",
    "labring": "Sealos/环界云",
    "polarismesh": "腾讯",
    "openmmlab": "商汤科技/上海人工智能实验室",
    # Universities / Research (mark as non-company)
    "thudm": "清华大学(学术)",
    "pku-yuangroup": "北京大学(学术)",
    "hpcaitech": "潞晨科技",
}

# Domain → company name hints (for blog field matching)
DOMAIN_COMPANY_MAP = {
    "google.com": "Google",
    "microsoft.com": "Microsoft",
    "meta.com": "Meta",
    "apple.com": "Apple",
    "amazon.com": "Amazon",
    "nvidia.com": "NVIDIA",
    "intel.com": "Intel",
    "ibm.com": "IBM",
    "redhat.com": "Red Hat (IBM)",
    "oracle.com": "Oracle",
    "sap.com": "SAP",
    "salesforce.com": "Salesforce",
    "alibaba-inc.com": "阿里巴巴",
    "tencent.com": "腾讯",
    "baidu.com": "百度",
    "bytedance.com": "字节跳动",
    "huawei.com": "华为",
    "jd.com": "京东",
    "xiaomi.com": "小米",
    "databricks.com": "Databricks",
    "elastic.co": "Elastic",
    "hashicorp.com": "HashiCorp",
    "docker.com": "Docker Inc.",
    "vmware.com": "VMware (Broadcom)",
    "confluent.io": "Confluent",
    "cockroachlabs.com": "Cockroach Labs",
    "pingcap.com": "PingCAP",
    "vercel.com": "Vercel",
    "supabase.com": "Supabase",
    "cloudflare.com": "Cloudflare",
    "grafana.com": "Grafana Labs",
    "influxdata.com": "InfluxData",
    "datadoghq.com": "Datadog",
    "sentry.io": "Sentry",
    "jetbrains.com": "JetBrains",
    "shopify.com": "Shopify",
    "uber.com": "Uber",
    "airbnb.com": "Airbnb",
    "stripe.com": "Stripe",
    "huggingface.co": "Hugging Face",
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "mistral.ai": "Mistral AI",
    "stability.ai": "Stability AI",
    "canonical.com": "Canonical",
    "suse.com": "SUSE",
    "gitlab.com": "GitLab",
    "atlassian.com": "Atlassian",
}


def github_api(endpoint):
    """Call GitHub API with token auth. Returns parsed JSON or None."""
    token = os.environ.get("GITHUB_TOKEN", "")
    url = f"https://api.github.com{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    if token:
        req.add_header("Authorization", f"token {token}")
    req.add_header("User-Agent", "oss-x-tracer")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # Rate limit — wait and retry once
            reset = e.headers.get("X-RateLimit-Reset")
            if reset:
                wait = max(int(reset) - int(time.time()), 1)
                wait = min(wait, 60)  # cap at 60s
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except Exception:
                    return None
        return None
    except Exception:
        return None


def extract_github_owner(url):
    """Extract GitHub owner from URL."""
    parsed = urlparse((url or "").strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    if host != "github.com":
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return parts[0].lower() if parts else None


def lookup_known_company(owner):
    """Layer 1: Static mapping lookup."""
    owner_lower = owner.strip().lower()
    if owner_lower in KNOWN_COMPANIES:
        return KNOWN_COMPANIES[owner_lower]
    # Try without hyphens/underscores
    normalized = owner_lower.replace("-", "").replace("_", "")
    for key, company in KNOWN_COMPANIES.items():
        if key.replace("-", "").replace("_", "") == normalized:
            return company
    return None


def infer_company_from_domain(blog_url):
    """Try to match blog/website domain to a known company."""
    if not blog_url:
        return None
    parsed = urlparse(blog_url if "://" in blog_url else f"https://{blog_url}")
    host = (parsed.hostname or "").lower().lstrip("www.")
    # Direct domain match
    if host in DOMAIN_COMPANY_MAP:
        return DOMAIN_COMPANY_MAP[host]
    # Try parent domain (e.g., cloud.google.com → google.com)
    parts = host.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[-2:])
        if parent in DOMAIN_COMPANY_MAP:
            return DOMAIN_COMPANY_MAP[parent]
    return None


def query_org_profile(owner, cache=None):
    """
    Layer 2: Query GitHub API for org profile.
    Returns (company_name, evidence) or (None, None).
    Uses cache to avoid repeated API calls.
    """
    # Check cache first
    if cache is not None and owner.lower() in cache:
        cached = cache[owner.lower()]
        return cached.get("company"), cached.get("evidence")

    data = github_api(f"/orgs/{owner}")
    if not data:
        # Cache the miss too so we don't retry
        if cache is not None:
            cache[owner.lower()] = {"company": None, "evidence": None}
        return None, None

    org_name = data.get("name", "")
    company_field = (data.get("company") or "").strip()
    blog_field = (data.get("blog") or "").strip()
    description = (data.get("description") or "").strip()

    company, evidence = None, None

    # 1. Org has explicit company field
    if company_field:
        known = lookup_known_company(company_field.replace(" ", "").replace(",", ""))
        if known:
            company = known
            evidence = f"GitHub org company字段: '{company_field}' → {known}"
        else:
            company = company_field
            evidence = f"GitHub org company字段: '{company_field}'"

    # 2. Blog domain maps to a known company
    elif blog_field:
        comp = infer_company_from_domain(blog_field)
        if comp:
            company = comp
            evidence = f"GitHub org blog域名: {blog_field} → {comp}"

    # 3. Description contains strong company signals
    if not company and description:
        for keyword in ["Inc.", "Inc,", "Ltd.", "Ltd,", "Corp.", "GmbH",
                        "LLC", "Co.", "公司", "集团", "科技"]:
            if keyword in description:
                evidence = f"GitHub org描述含商业关键词但未确定: '{description}'"
                break

    # Save to cache
    if cache is not None:
        cache[owner.lower()] = {"company": company, "evidence": evidence}

    return company, evidence


def main():
    parser = argparse.ArgumentParser(
        description="Trace company affiliations for repos (step ⑩)"
    )
    parser.add_argument("csv_file", help="Path to repo_exp.csv")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    # Read repos
    rows = []
    with open(args.csv_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    if not rows:
        print("No rows to process.", file=sys.stderr)
        sys.exit(0)

    # Group repos by owner for batch processing
    owner_repos = defaultdict(list)
    for i, row in enumerate(rows):
        owner = extract_github_owner(row.get("上游地址", ""))
        owner_repos[owner or f"__noowner_{i}"].append(i)

    # Track results per owner (so we query API once per org)
    owner_results = {}  # owner → (company, evidence, confidence, method)

    stats = {"layer1": 0, "layer2": 0, "unknown": 0}

    # Load org profile cache
    org_cache = _load_org_cache()

    unique_owners = [o for o in owner_repos if not o.startswith("__noowner_")]
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("WARNING: GITHUB_TOKEN not set. API rate limit is 60/hour (very slow).",
              file=sys.stderr)

    # Count how many need API calls
    need_api = sum(1 for o in unique_owners
                   if not lookup_known_company(o) and o.lower() not in org_cache)
    cached_api = sum(1 for o in unique_owners
                     if not lookup_known_company(o) and o.lower() in org_cache)

    print(f"Processing {len(rows)} repos from {len(unique_owners)} unique owners...",
          file=sys.stderr)
    print(f"  Layer 1 (known mapping) will resolve instantly", file=sys.stderr)
    print(f"  Layer 2 (API): {cached_api} cached, {need_api} need API calls", file=sys.stderr)

    save_interval = 20
    api_calls = 0

    for owner in sorted(owner_repos.keys()):
        if owner.startswith("__noowner_"):
            owner_results[owner] = ("unknown", "非GitHub URL", "", "非GitHub")
            stats["unknown"] += len(owner_repos[owner])
            continue

        # Layer 1: Known mapping
        company = lookup_known_company(owner)
        if company:
            owner_results[owner] = (company, f"已知企业映射: {owner} → {company}", "S", "已知映射")
            stats["layer1"] += len(owner_repos[owner])
            continue

        # Layer 2: GitHub API org profile (with cache)
        company, evidence = query_org_profile(owner, cache=org_cache)
        api_calls += 1
        if api_calls % save_interval == 0:
            _save_org_cache(org_cache)
            print(f"  Progress: {api_calls} API lookups done...", file=sys.stderr)

        if company:
            owner_results[owner] = (company, evidence, "A", "GitHub API")
            stats["layer2"] += len(owner_repos[owner])
            continue

        # If API returned some hint but not a definitive answer
        if evidence:
            owner_results[owner] = ("unknown", evidence, "", "待LLM确认")
            stats["unknown"] += len(owner_repos[owner])
        else:
            owner_results[owner] = ("unknown", "API无company信息", "", "待LLM研究")
            stats["unknown"] += len(owner_repos[owner])

    # Save cache at the end
    _save_org_cache(org_cache)

    # Apply results to rows
    output_fields = list(rows[0].keys()) + [
        "company_name", "evidence", "confidence", "trace_method"
    ]

    for owner, indices in owner_repos.items():
        company, evidence, confidence, method = owner_results[owner]
        for i in indices:
            rows[i]["company_name"] = company
            rows[i]["evidence"] = evidence
            rows[i]["confidence"] = confidence
            rows[i]["trace_method"] = method

    # Write output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in output_fields})

    # Summary
    if args.summary:
        from collections import Counter
        companies = Counter(r.get("company_name", "unknown") for r in rows)
        methods = Counter(r.get("trace_method", "") for r in rows)

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Company Tracing Summary (Step ⑩)", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Total repos:         {len(rows)}", file=sys.stderr)
        print(f"  Layer 1 (已知映射):   {stats['layer1']}", file=sys.stderr)
        print(f"  Layer 2 (GitHub API): {stats['layer2']}", file=sys.stderr)
        print(f"  Unknown (待LLM):      {stats['unknown']}", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)
        print(f"  By company (top 20):", file=sys.stderr)
        for name, count in companies.most_common(20):
            if name != "unknown":
                print(f"    {name:40s} {count}", file=sys.stderr)
        unknown_count = companies.get("unknown", 0)
        print(f"    {'unknown':40s} {unknown_count}", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)
        print(f"  By method:", file=sys.stderr)
        for method, count in methods.most_common():
            print(f"    {method:40s} {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
