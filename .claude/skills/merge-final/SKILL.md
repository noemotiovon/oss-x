---
name: merge-final
description: Merge all pipeline outputs into the final unified table
user-invocable: true
---

# Final Merge Skill (Step ⑧)

Merge all pipeline outputs into a single final.csv containing repos, organizations, companies, and foundations with cross-references.

## Input

All of the following (missing files are skipped):
- `output/all_repos.csv` — seed repos
- `output/org_expanded_repos.csv` — repos from org expansion (step ⑥)
- `output/foundation_expanded_repos.csv` — repos from foundation expansion (step ⑦)
- `output/organizations.csv` — verified organizations (step ③)
- `output/companies.csv` — companies (step ④)
- `output/foundations_deduped.csv` — foundations (step ⑦)

## Procedure

### Step 1: Verify inputs

Check which input files exist. Warn the user about any missing files — these represent pipeline steps that haven't been completed.

### Step 2: Run the merge script

```bash
python3 scripts/merge_final.py -o output/final.csv --summary
```

### Step 3: Review output

Print a summary of:
- Total entities by type (repo, organization, company, foundation)
- Coverage statistics (how many repos have organization/company/foundation assigned)
- Any repos with no organization assigned

### Step 4: Present to user

Show the final statistics and ask if the user wants to review specific sections or re-run any upstream steps to improve coverage.

## Output Schema

`output/final.csv` columns:

| Column | Description |
|--------|-------------|
| name | Entity name |
| url | Standardized URL |
| type | repo / organization / company / foundation |
| category | Original classification (e.g., 训练加速) |
| organization | Parent GitHub organization |
| company | Parent company (may be empty) |
| foundation | Parent foundation (may be empty) |
| stars | GitHub stars (repos only) |
| last_active | Last push date (repos only) |
| description | Entity description |
| evidence | Evidence/source for classifications |
