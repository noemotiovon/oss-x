---
name: resolve-unknown-orgs
description: Resolve unknown org affiliations using script (GitHub API fork/org lookup) and LLM Web Search for remaining
user-invocable: true
---

# Unknown Org Resolution Skill (Step ⑤)

For repos in `repo_unknown_org.csv` that have no known GitHub organization, find their org affiliation using automated methods first, then LLM for remaining.

## Input

- `output/repo_unknown_org.csv` — from step ④ `/resolve-orgs`

## Procedure

### Step 1: Run the resolution script

```bash
python3 scripts/resolve_unknown_orgs.py output/repo_unknown_org.csv \
    -o output/repo_unknown_org.csv --summary
```

The script applies 3 layers for `user` type owners:

1. **Layer 1 — Fork source**: Check if any repo is a fork → use source repo's org
2. **Layer 2 — User org membership**: Query `GET /users/{user}/orgs` → if user belongs to exactly 1 org, use it
3. **Layer 3 — Repo migration**: Check if repo has been transferred to a different org

### Step 2: Review script results

Check the summary:
- How many resolved by script?
- How many remain unknown?

If all resolved, skip to Step 4.

### Step 3: LLM Web Search for remaining unknowns

For repos still without org affiliation, **use Web Search**. Do NOT guess.

#### For each repo:

1. **Web search** for `"{project_name}" organization` or `"{project_name}" maintained by`
2. **Determine the parent organization**
3. **Record**:
   - `org_name` — organization name
   - `org_url` — organization URL (GitHub preferred)
   - `evidence` — actual facts and URLs
   - `confidence` — S/A/B/C

### Step 4: Present to user

Show results in a table for review. The user may correct org assignments.

After user confirmation, save updated `output/repo_unknown_org.csv`.

### Step 5: Output summary

Print:
- Total repos processed
- Resolved by script vs LLM
- Count by confidence level

### Next step

→ `/merge-orgs`
