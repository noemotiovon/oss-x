---
name: expand-orgs
description: Expand verified organizations into their individual repos and generate org_expanded_repos.csv
user-invocable: true
---

# Org Expansion Skill (Step ⑥)

Read `output/organizations.csv` (human-verified organizations from step ③), expand each org into its notable GitHub repos, and output `output/org_expanded_repos.csv`.

## Input

- `output/organizations.csv` — verified organizations (from `/resolve-orgs`)
- `output/all_repos.csv` — existing repo pool for deduplication (optional)
- User may optionally specify:
  - `--min-stars N` — minimum stars for active repos (default: 10)
  - `--min-stars-popular N` — stars threshold to always include regardless of activity (default: 500)

## Procedure

### Step 1: Run the expansion script

```bash
python3 scripts/expand_orgs.py output/organizations.csv \
    --existing output/all_repos.csv \
    --summary -o output/org_expanded_repos.csv
```

- If exit code is **0** — all organizations expanded successfully, go to Step 3.
- If exit code is **1** — some organizations have non-GitHub URLs and need manual handling, proceed to Step 2.

### Step 2: LLM expansion (fallback for non-GitHub organizations)

For organizations the script cannot handle (non-GitHub platforms), you MUST research each one to find their repos.

#### Research methodology

For each non-GitHub org:

1. **Web search** for `"{org_name}" github organization` or `"{org_name}" source code repositories`
2. **Identify the GitHub org** — most projects have a GitHub mirror even if they have their own site
3. **If a GitHub org is found**, run the script again with that org, or manually list their key repos
4. **If no GitHub org exists**, list their key repos from whatever hosting they use

#### Filtering criteria

Only include repos that meet ALL of these:
- **Not archived** — still accepting contributions
- **Actively maintained** — pushed to within the last year, OR
- **Widely used** — 500+ stars even if less active
- **Not a fork** — unless the fork is significantly more popular than the upstream
- **Minimum 10 stars** — filters out empty/test repos

#### What to include for each repo

| Field | Value |
|-------|-------|
| 页签 | Inherited from the parent organization |
| 项目名称 | Repo name |
| 分类 | Inherited from the parent organization |
| 上游地址 | Full GitHub/GitLab URL |
| entity_type | `repo` |
| reason | `LLM展开: {parent_org_name}, ⭐{stars}` |
| source_org | Parent organization name |
| stars | Star count |
| description | Repo description |

After manually adding repos, append them to `output/org_expanded_repos.csv` ensuring no URL duplicates.

### Step 3: Output summary

Print a summary table:
- Total new repos discovered
- How many were expanded from each organization
- Any organizations that could not be expanded

### Step 4: Review with user

Present the expansion results to the user for review. Key things to highlight:
- Orgs with very many repos — user may want to raise the star threshold
- Orgs with zero qualifying repos — may need manual investigation
- Any non-GitHub organizations that were handled manually
