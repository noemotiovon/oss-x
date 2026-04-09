---
name: merge-orgs
description: Merge all organization sources into a single deduplicated org_exp.csv
user-invocable: true
---

# Organization Merge Skill (Step ⑥)

Merge organizations from three sources into a single deduplicated list.

## Input

- `output/organization.csv` — from step ③ (entities originally classified as organization)
- `output/repo_known_org.csv` — from step ④ (orgs found via GitHub API)
- `output/repo_unknown_org.csv` — from step ⑤ (orgs found via LLM + human)

## Procedure

### Step 1: Run the merge script

```bash
python3 scripts/merge_orgs.py output/organization.csv output/repo_known_org.csv output/repo_unknown_org.csv \
    -o output/org_exp.csv --summary
```

The script:
1. Reads all three input files
2. Extracts organization info from each source
3. Deduplicates by org name/URL (case-insensitive)
4. Preserves the column structure from `repo_known_org.csv`:
   - `org_name`, `org_url`, `repo_count`, `页签(聚合)`, `项目名称(聚合)`, `分类(聚合)`, `上游地址(聚合)`
5. Merges repo counts and aggregated fields for duplicate orgs

### Step 2: Verify output

Check `output/org_exp.csv`:
- No duplicate organizations
- All sources are represented

### Step 3: Output summary

Print:
- Total unique organizations
- Count from each source
- Any duplicates that were merged

### Next step

→ `/validate-orgs`
