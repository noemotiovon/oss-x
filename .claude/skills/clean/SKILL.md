---
name: clean
description: Validate and clean data.csv URLs via GitHub API, flag invalid/non-GitHub/mirror entries
user-invocable: true
---

# Data Cleaning & URL Validation (Step ⓪)

Validate all URLs in `data.csv` via GitHub API, collect repo activity metrics, and flag problematic entries for human review.

## Input

CSV file at `data.csv` with columns: `页签,序号,项目名称,分类,上游地址`

## Procedure

### Step 1: Run the cleaning script

```bash
python3 scripts/clean.py data.csv -o output/cleaned.csv --summary
```

This script:
1. Parses each row's上游地址 (upstream URL)
2. For GitHub repo URLs (`github.com/{owner}/{repo}`): calls GitHub API to validate existence, fetches `open_issues_count`, total PR count, fork/archived/mirror status
3. For GitHub org URLs (`github.com/{owner}`): validates org existence
4. Flags non-GitHub URLs, invalid URLs, and entries with no URL
5. Detects redirected repos (renamed/transferred) and reports the actual URL

Results are cached in `output/.cache/github_clean_cache.json` for resumability.

### Step 2: Review output

Check `output/cleaned.csv` columns:
- `status`: `valid`, `valid_user`, `not_found`, `non_github`, `no_url`
- `url_type`: `repo`, `org`, `user`, `non_github`, or empty
- `actual_url`: populated only if the repo was redirected (renamed/transferred)
- `open_issues_count`: open issues + open PRs (GitHub combines them)
- `total_pull_requests`: total PRs (all states) — **0 PRs suggests mirror repo**
- `fork`: whether GitHub marks it as a fork
- `archived`: whether the repo is archived
- `mirror_url`: populated if GitHub knows it's a mirror
- `has_issues`: whether issues are enabled — **disabled suggests mirror**
- `note`: additional flags (multi-URL, non-GitHub, etc.)

### Step 3: Report to user

Summarize findings and highlight entries that need human attention:
1. **Not found** — URL is invalid or repo/org deleted
2. **Non-GitHub** — need manual verification or GitHub mirror lookup
3. **No URL** — data quality issue
4. **Potential mirrors** — repos with 0 PRs and issues disabled
5. **Redirected** — URL has changed, suggest updating data.csv
6. **Archived** — repo is no longer active

### Next step

→ After human review: `/fix-urls` (to resolve problematic URLs), then `/classify`
