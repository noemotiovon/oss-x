---
name: classify
description: Classify entities from data.csv into repo, organization, or unknown using GitHub API
user-invocable: true
---

# Entity Classification Skill (Step ①)

Read `data.csv` and classify each entry into **repo**, **organization**, or **unknown** using GitHub API.

## Input

CSV file at `data.csv` with columns: `页签,序号,项目名称,*分类,*上游地址`

## Procedure

### Step 1: Run the classification script

```bash
python3 scripts/classify.py data.csv --summary -o output/classified.csv
```

This script:
1. Parses each row's上游地址 (upstream URL)
2. If URL matches `github.com/{owner}/{repo}` format → calls `GET /repos/{owner}/{repo}` → type = `repo`
3. If URL matches `github.com/{owner}` format (no repo name) → calls `GET /orgs/{owner}` → type = `organization`
4. If API returns 404 or URL is not GitHub → type = `unknown`

### Step 2: Verify output

Check that `output/classified.csv` exists and contains the columns:
`页签,序号,项目名称,分类,上游地址,type,reason`

Where:
- `type` is one of: `repo`, `organization`, `unknown`
- `reason` describes how the classification was determined (e.g., `GitHub API: repo exists`, `GitHub API: org exists`, `非GitHub URL`)

### Step 3: Output summary

Print a summary:
- Total entries
- Count by type (repo / organization / unknown)
- If there are `unknown` entries, inform the user to run `/classify-unknown` next

### Next step

→ If unknowns exist: `/classify-unknown`
→ If no unknowns: `/split-merge`
