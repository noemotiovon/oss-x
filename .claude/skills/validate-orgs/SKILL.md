---
name: validate-orgs
description: Validate whether each organization is a meaningful open-source organization
user-invocable: true
---

# Organization Validation Skill (Step ⑦)

Determine whether each organization in `org_exp.csv` is a valid, meaningful open-source organization.

## Input

- `output/org_exp.csv` — from step ⑥ `/merge-orgs`

## Procedure

### Step 1: Run the validation script

```bash
python3 scripts/validate_orgs.py output/org_exp.csv -o output/org_exp_val.csv --summary
```

The script handles **Layer 1 — auto-validation**:
- If org's `repo_count > 1` in the CSV → `is_valid=true`, `validation_method=脚本(repo数量>1)`
- Remaining orgs are marked for further validation

### Step 2: GitHub API validation (Layer 2)

For orgs that are on GitHub and not auto-validated:

1. Call GitHub API to get org statistics:
   - Total public repositories
   - Repos with star > 100 (count)
   - Active repos (pushed within last year, count)
2. Record these stats in the CSV columns:
   - `total_repos`, `star_gt100`, `active_repos`
   - `validation_method=GitHub API`

Present these orgs to the user with their stats. The user decides `is_valid=true` or `is_valid=false`.

### Step 3: LLM Web Search validation (Layer 3)

For orgs that are NOT on GitHub (non-GitHub platforms):

1. **Use Web Search** to find information about the organization
2. List their known repositories/projects
3. Record:
   - `validation_evidence` — what was found
   - `validation_method=LLM`

Present these orgs to the user with the search results. The user decides `is_valid=true` or `is_valid=false`.

### Step 4: Save results

After user decisions, write `output/org_exp_val.csv` with all columns from `org_exp.csv` plus:

| Column | Description |
|--------|-------------|
| `is_valid` | `true` or `false` |
| `total_repos` | Total public repos (GitHub API) |
| `star_gt100` | Repos with >100 stars (GitHub API) |
| `active_repos` | Repos active in last year (GitHub API) |
| `validation_method` | `脚本(repo数量>1)` / `GitHub API` / `LLM` |
| `validation_evidence` | Supporting evidence |

### Step 5: Output summary

Print:
- Total organizations
- Valid count (and breakdown by validation method)
- Invalid count
- Orgs validated by script vs GitHub API vs LLM

### Next step

→ `/expand-repos`
