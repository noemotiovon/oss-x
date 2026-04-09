---
name: split-merge
description: Split classified and unknown results by type into repo.csv and organization.csv
user-invocable: true
---

# Split & Merge Skill (Step ③)

Split entries from `classified.csv` and `unknown.csv` by type into separate `repo.csv` and `organization.csv` files.

## Input

- `output/classified.csv` — from step ① (type=repo and type=organization rows)
- `output/unknown.csv` — from step ② (human-confirmed type assignments)

## Procedure

### Step 1: Run the split-merge script

```bash
python3 scripts/split_merge.py output/classified.csv output/unknown.csv -o output
```

If `output/unknown.csv` doesn't exist yet (step ② not done or no unknowns):

```bash
python3 scripts/split_merge.py output/classified.csv -o output
```

The script:
1. Reads both input files
2. Rows with `type=repo` → `output/repo.csv`
3. Rows with `type=organization` → `output/organization.csv`
4. Deduplicates by上游地址 (URL)

### Step 2: Verify output

Check both files exist and have no duplicates:
- `output/repo.csv` — all repos
- `output/organization.csv` — all organizations

### Step 3: Output summary

Print:
- Total repos in `repo.csv`
- Total organizations in `organization.csv`
- Any duplicates removed

### Next step

→ `/resolve-orgs` (to resolve repo → org relationships)
