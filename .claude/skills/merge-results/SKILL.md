---
name: merge-results
description: Merge repo_exp, foundation, and company into a final summary table
user-invocable: true
---

# Result Merge Skill (Step ⑪)

Merge `repo_exp.csv`, `foundation.csv`, and `company.csv` into a single clean summary table.

## Input

- `output/repo_exp.csv` — expanded repo list (from step ⑧)
- `output/foundation.csv` — foundation affiliations (from step ⑨)
- `output/company.csv` — company affiliations (from step ⑩)

## Output

- `output/result.csv` — final summary table

## Output Columns

| Column | Source | Description |
|--------|--------|-------------|
| `页签` | repo_exp | Tab/label from input data |
| `项目名称` | repo_exp | Project name |
| `repo` | repo_exp | GitHub repo URL (`上游地址`) |
| `organization` | repo_exp | GitHub org (extracted from `上游地址`, e.g. `huggingface` from `github.com/huggingface/transformers`) |
| `foundation` | foundation | `foundation_name` column (or `none`) |
| `company` | company | `company_name` column (or `unknown`) |

## Procedure

### Step 1: Run the merge script

```bash
python3 scripts/merge_results.py \
    output/repo_exp.csv \
    output/foundation.csv \
    output/company.csv \
    -o output/result.csv \
    --summary
```

### Step 2: Verify output

Check `output/result.csv`:
- Row count matches `repo_exp.csv`
- No missing `repo` values
- `foundation` and `company` columns are filled (may be `none`/`unknown`)

### Step 3: Output summary

Print:
- Total repos in final table
- Repos with foundation affiliation (count, excluding `none`)
- Repos with company affiliation (count, excluding `unknown`)
- Breakdown by `页签` (tab/label)

### Next step

→ This is the final step. `output/result.csv` is the deliverable.
