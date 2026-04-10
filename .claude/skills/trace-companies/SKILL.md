---
name: trace-companies
description: Trace company affiliation for each repo using script (known mapping + GitHub API) and LLM Web Search for remaining unknowns
user-invocable: true
---

# Company Tracing Skill (Step ⑩)

Determine which repos are backed by commercial companies. Uses a 3-layer strategy: known mapping → GitHub API → LLM.

## Input

- `output/repo_exp.csv` — expanded repo list (from step ⑧)

## Procedure

### Step 1: Run the tracing script

```bash
python3 scripts/trace_companies.py output/repo_exp.csv -o output/company.csv --summary
```

The script applies 3 layers automatically:

1. **Layer 1 — Known company mapping**: Static dict mapping ~150+ GitHub orgs to companies (e.g., `huggingface` → Hugging Face, `alibaba` → 阿里巴巴). Confidence = S.
2. **Layer 2 — GitHub API org profile**: Queries `GET /orgs/{owner}` for the `company`, `blog`, `description` fields. Uses `company` field directly, or infers from blog domain. Confidence = A.
3. **Layer 3 — Mark unknown**: Repos not resolved by Layer 1/2 are marked `company_name=unknown, trace_method=待LLM研究`.

### Step 2: Review script results

Check the summary output:
- How many repos were resolved by Layer 1 (known mapping)?
- How many by Layer 2 (GitHub API)?
- How many remain unknown?

If all repos are resolved (unknown = 0), skip to Step 4.

### Step 3: LLM Web Search for remaining unknowns

For repos still marked `unknown`, **use Web Search** to determine company affiliation. Do NOT guess.

#### Batch optimization

- Group unknown repos by GitHub org — repos in the same org belong to the same company
- Research the org once, apply to all its repos

#### For each unknown org/repo:

1. **Web search** for `"{org_name}" company` or `"{project_name}" developed by`
2. Determine: which company (if any) owns/maintains this?
3. Record:
   - `company_name` — company name, or `unknown` if truly independent
   - `evidence` — actual URLs and facts from search
   - `confidence` — S/A/B/C

#### Decision criteria

- **Has parent company**: owned/maintained by a for-profit company → record it
- **Independent project**: community-driven, no single corporate owner → `unknown`
- **University labs**: not companies → `unknown`

### Step 4: Present to user

Show results grouped by company for review. The user may correct assignments.

After user confirmation, update `output/company.csv`.

### Step 5: Output summary

Print:
- Total repos processed
- Repos resolved by script (Layer 1 + Layer 2) vs LLM (Layer 3)
- Company distribution (count by company)
- Count by confidence level
