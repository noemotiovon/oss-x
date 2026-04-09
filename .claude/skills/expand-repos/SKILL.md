---
name: expand-repos
description: Expand repos from original organizations using GitHub API and LLM Web Search
user-invocable: true
---

# Repo Expansion Skill (Step ⑧)

Starting from the original repo list and original organizations (from `organization.csv`), discover additional popular and active repositories.

## Input

- `output/repo.csv` — original repo list (from step ③)
- `output/organization.csv` — original organization list (from step ③)

## Procedure

### Step 1: Run the expansion script

```bash
python3 scripts/expand_repos.py output/repo.csv output/organization.csv \
    -o output/repo_exp.csv --summary
```

The script:
1. Copies all `repo.csv` entries with `source=repo`
2. For each GitHub org in `organization.csv`:
   - Calls GitHub Search API to find repos with **stars > 100 AND pushed in last year**
   - Adds them with `source=org_expansion`
3. Deduplicates: if a repo exists in both repo.csv and expansion, keeps `source=repo` (original takes priority)

### Step 2: LLM expansion for non-GitHub orgs

For organizations NOT on GitHub:

1. **Use Web Search** to find their popular repositories
2. Search for: `"{org_name}" popular repositories` or `"{org_name}" open source projects`
3. Add found repos with:
   - `source=org_expansion`
   - `llm_note=LLM搜集` (to mark these were found via LLM, not API)
4. Present LLM-found repos to user for review before adding

### Step 3: Present expansion results to user

Show:
- Original repos count (from repo.csv)
- New repos discovered (from org expansion)
- Repos by organization
- Filter criteria applied (stars > 100, active in last year)

The user reviews and may remove irrelevant repos.

### Step 4: Save final output

After user confirmation, save `output/repo_exp.csv` with columns:
- All original columns from repo.csv
- `source` — `repo` (original) or `org_expansion` (expanded)
- `llm_note` — notes for LLM-discovered repos (empty for API-discovered)
- `expanded_from_org` — which org this was expanded from (empty for original repos)

### Step 5: Output summary

Print:
- Total repos in repo_exp.csv
- Original repos vs expanded repos
- Repos by organization

### Next step

→ `/trace-foundations` and `/trace-companies` (can run in parallel)
