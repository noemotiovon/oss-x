---
name: expand-foundations
description: Deduplicate foundations and expand into their notable repos
user-invocable: true
---

# Foundation Expansion Skill (Step ⑦)

Deduplicate foundations, then expand each one into its notable open-source projects.

## Input

- `output/foundations.csv` — foundation list (from step ⑤)

## Procedure

### Step 1: Deduplicate foundations

```bash
python3 scripts/dedup_foundations.py output/foundations.csv \
    -o output/foundations_deduped.csv --summary
```

### Step 2: LLM-driven expansion of foundation projects

For each foundation in `output/foundations_deduped.csv`, research and list their notable open-source projects.

#### Research methodology

For each foundation:

1. **Check the foundation's project page**:
   - CNCF: `landscape.cncf.io` — lists all graduated, incubating, and sandbox projects
   - Apache: `projects.apache.org` — lists all Apache projects
   - Linux Foundation: `linuxfoundation.org/projects` — lists LF projects
   - Eclipse: `projects.eclipse.org` — lists all Eclipse projects
   - OpenJS: `openjsf.org/projects` — lists all OpenJS projects

2. **Web search** for `"{foundation_name}" projects list` or `"{foundation_name}" notable projects`

3. **Filter for notable projects** — only include projects that are:
   - Actively maintained (recent commits)
   - Widely adopted (significant user base or stars)
   - Not already in `output/all_repos.csv`

#### What to record for each discovered repo

| Field | Value |
|-------|-------|
| 页签 | Leave empty (discovered via foundation expansion) |
| 项目名称 | Project/repo name |
| 分类 | Best guess based on project function |
| 上游地址 | GitHub URL (preferred) or project URL |
| entity_type | `repo` |
| reason | `基金会展开: {foundation_name}` |
| source_foundation | Foundation name |
| stars | Star count (if GitHub) |
| description | Project description |

### Step 3: Present to user for review

Show the expansion results grouped by foundation:
- Foundation name
- Number of projects discovered
- List of projects with stars and descriptions

The user should confirm which projects to include.

### Step 4: Generate output

After user confirmation, generate `output/foundation_expanded_repos.csv` with the approved repos.

Verify no duplicates against `output/all_repos.csv` and `output/org_expanded_repos.csv`.
