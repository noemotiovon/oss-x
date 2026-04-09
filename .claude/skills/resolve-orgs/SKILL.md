---
name: resolve-orgs
description: Resolve repos to their parent organizations via GitHub API, split into known and unknown org results
user-invocable: true
---

# Repo Organization Resolution Skill (Step ④)

For each repo in `repo.csv`, query GitHub API to find its parent organization. Split results into known-org (aggregated) and unknown-org files.

## Input

- `output/repo.csv` — from step ③ `/split-merge`

## Procedure

### Step 1: Run the resolution script

```bash
python3 scripts/resolve_orgs.py output/repo.csv --summary -o output
```

The script:
1. For each repo, calls GitHub API to get `owner` info
2. If `owner.type == Organization` → records the org name and URL
3. **Known org repos**: groups by org, aggregates:
   - `org_name` — organization name
   - `org_url` — organization GitHub URL
   - `repo_count` — number of repos under this org
   - `页签` — aggregated (semicolon-joined)
   - `项目名称` — aggregated (semicolon-joined)
   - `分类` — aggregated (semicolon-joined)
   - `上游地址` — aggregated (semicolon-joined)
4. **Unknown org repos**: repos where API cannot determine org (personal accounts, non-GitHub URLs) → kept as-is, not aggregated

### Step 2: Verify output

Check that both files exist:
- `output/repo_known_org.csv` — aggregated by organization
- `output/repo_unknown_org.csv` — repos without known organization

### Step 3: Output summary

Print:
- Total repos processed
- Repos with known org (count + org count)
- Repos with unknown org (count)
- Top organizations by repo count

### Next step

→ If unknown orgs exist: `/resolve-unknown-orgs`
→ If no unknowns: `/merge-orgs`
