---
name: classify-unknown
description: Classify unknown entities using script (GitHub Search + PyPI + URL patterns) and LLM Web Search for remaining
user-invocable: true
---

# Unknown Classification Skill (Step ②)

For entries marked `unknown` in `output/classified.csv`, classify them as **repo** or **organization** using automated methods first, then LLM for remaining.

## Input

- `output/classified.csv` — from step ① `/classify`

## Procedure

### Step 1: Run the classification script

```bash
python3 scripts/classify_unknown.py output/classified.csv -o output/unknown.csv --summary
```

The script applies 4 layers:

1. **Layer 0 — Known entries**: Static mapping of common projects (e.g., LVS → repo, OpenFOAM → repo)
2. **Layer 1 — GitHub Search API**: Fuzzy search by project name, accept if top result matches and has ≥10 stars
3. **Layer 2 — PyPI search**: Check if project exists as a PyPI package
4. **Layer 3 — URL pattern heuristics**: Detect download links (.tar.gz), software hosting patterns, project websites

### Step 2: Review script results

Check the summary output:
- How many resolved by script?
- How many remain unknown?

If all entries are resolved (remaining = 0), skip to Step 4.

### Step 3: LLM Web Search for remaining unknowns

For entries still marked `unknown`, **use Web Search** to classify. Do NOT guess.

#### For each unknown entry:

1. **Web search** for the project name and URL
2. **Determine type**:
   - Single software project / codebase → `repo`
   - Group/community maintaining multiple repos → `organization`
3. **Record evidence**: actual URLs and facts found
4. **Assign confidence**: S/A/B/C

#### Decision guidelines

**repo signals**:
- Has a single codebase you can clone or download
- Installable as one package
- Project-specific website for ONE codebase
- Kernel subsystems (KVM, LVS) are repos

**organization signals**:
- Maintains multiple independent repositories
- Name ends with "社区"/"community"

### Step 4: Present to user

Show results in a table for review. The user may correct any entries.

After user confirmation, save the final `output/unknown.csv`.

### Step 5: Output summary

Print:
- Total unknowns processed
- Resolved by script vs LLM
- Count by type (repo / organization)

### Next step

→ `/split-merge`
