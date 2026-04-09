---
name: resolve-unknown-orgs
description: Use LLM Web Search to find organization info for repos without known GitHub org
user-invocable: true
---

# Unknown Org Resolution Skill (Step ⑤)

For repos in `repo_unknown_org.csv` that have no known GitHub organization, use Web Search to find their organization affiliation.

## Input

- `output/repo_unknown_org.csv` — from step ④ `/resolve-orgs`

## Procedure

### Step 1: Read unknown org repos

Read `output/repo_unknown_org.csv`. If empty, inform user and skip.

### Step 2: LLM Web Search for each repo

For each repo, **you MUST use Web Search** to find its parent organization. Do NOT guess.

#### For each repo:

1. **Web search** for `"{project_name}" organization` or `"{project_name}" maintained by` or `"{project_name}" developed by`
2. **Determine the parent organization**:
   - Who maintains this project?
   - Is it part of a larger organization or community?
   - What GitHub org (if any) hosts related projects?
3. **Record**:
   - `org_name` — organization name
   - `org_url` — organization URL (GitHub preferred)
   - `evidence` — actual facts and URLs found via search
   - `confidence` — S/A/B/C rating

#### Confidence levels:

- **S** — Official source confirms org (e.g., project README says "maintained by X")
- **A** — Multiple reliable sources agree on the org
- **B** — Partial evidence, reasonable inference
- **C** — Weak evidence, best guess

### Step 3: Present to user

Show results in a table for each repo:
- Repo name and URL
- Suggested org name and URL
- Evidence summary
- Confidence level

The user will review and may correct org assignments.

### Step 4: Save results

After user confirmation, update `output/repo_unknown_org.csv` with the new columns:
`org_name, org_url, evidence, confidence`

### Step 5: Output summary

Print:
- Total repos processed
- Count by confidence level
- Any entries the user corrected

### Next step

→ `/merge-orgs`
