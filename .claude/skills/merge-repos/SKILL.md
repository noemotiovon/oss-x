---
name: merge-repos
description: Merge repos.csv and non_repos_classified.csv into all_repos.csv
user-invocable: true
---

# Merge Repos Skill (Between Steps ①② and ③④⑤)

Merge the repo sources from step ① (repos.csv) and step ② (non_repos_classified.csv) into a single all_repos.csv.

## Input

- `output/repos.csv` — repos identified in step ①
- `output/non_repos_classified.csv` — LLM + human classified entities from step ② (only type=repo rows are merged)

## Procedure

### Step 1: Verify inputs exist

Check that `output/repos.csv` exists. If `output/non_repos_classified.csv` does not exist, the merge still proceeds with repos.csv only.

### Step 2: Run the merge script

```bash
python3 scripts/merge_repos.py output/repos.csv output/non_repos_classified.csv \
    -o output/all_repos.csv --summary
```

If `output/non_repos_classified.csv` doesn't exist yet (step ② not done):

```bash
python3 scripts/merge_repos.py output/repos.csv -o output/all_repos.csv --summary
```

### Step 3: Verify output

Print the total count and confirm no URL duplicates exist.

### Step 4: Next steps

Inform the user that `output/all_repos.csv` is ready for:
- Step ③: `/resolve-orgs` — resolve repos to organizations
- Step ④: `/trace-companies` — trace company affiliations
- Step ⑤: `/trace-foundations` — trace foundation affiliations
