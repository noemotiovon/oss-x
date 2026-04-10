---
name: fix-urls
description: Fix problematic URLs (not_found, non_github, no_url, potential mirrors) via script filtering and LLM Web Search
user-invocable: true
---

# URL Fix & Resolution (Step ⓪-b)

Filter problematic entries from `cleaned.csv`, apply multi-layer deterministic resolution, and use LLM Web Search only for the remainder.

## Input

- `output/cleaned.csv` — from step ⓪ `/clean`

## Procedure

### Step 1: Run the fix script

```bash
python3 scripts/fix_urls.py output/cleaned.csv -o output/fix_urls.csv --summary
```

The script extracts 4 categories of problematic entries and applies 5 resolution layers:

**Categories:**
1. `not_found` — GitHub URL returns 404
2. `non_github` — URL points to GitLab, Gitee, SourceForge, Bioconductor, etc.
3. `no_url` — no valid URL provided
4. `potential_mirror` — valid GitHub repo but `has_issues == False` AND `total_pull_requests < 100`

**Resolution layers (script-first, LLM-last):**
- **L0 — Known mappings**: Static dict of well-known projects (e.g., LLVM, FFmpeg, PostgreSQL)
- **L1 — URL fix & retry**: Strip `.git` suffix, extract GitHub URL from multi-URL fields, retry API
- **L2 — GitHub Search API**: Fuzzy search by project name, accept top match with ≥10 stars
- **L3 — Bioconductor → GitHub**: For bioconductor.org URLs, search GitHub for the package dev repo
- **L4 — Mirror detection**: Fetch repo description/homepage, check "mirror" keywords, confirm or deny mirror status

Results are cached in `output/.cache/github_fix_cache.json` for resumability.

### Step 2: Review script output

Check `output/fix_urls.csv` columns:
- `reason`: why it was flagged
- `resolved_by`: which layer resolved it (empty = unresolved)
- `resolved_url`: the found URL
- `evidence`: how it was found
- `confidence`: S/A/B/C

Check the summary:
- How many resolved by script?
- How many remain for LLM?

If all resolved, skip to Step 4.

### Step 3: LLM Web Search for remaining unknowns

For entries still unresolved, **use Web Search**. Do NOT guess.

#### For each entry:
1. **Web search** for `"{project_name}" github` or `"{project_name}" official repository`
2. **Record**: `resolved_url`, `evidence` (actual URLs found), `confidence` (S/A/B/C)

### Step 4: Present to user

Show results in a table for review. The user may correct entries.

After user confirmation, save updated `output/fix_urls.csv`.

### Step 5: Report to user

Summarize:
- Total entries processed
- Resolved by script (by layer) vs LLM
- Confidence distribution (S/A/B/C)
- Unresolved entries

### Next step

→ After human review and approval: `/classify`
