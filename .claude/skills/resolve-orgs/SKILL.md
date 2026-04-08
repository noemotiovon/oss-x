---
name: resolve-orgs
description: Resolve repos into their parent organizations, deduplicate by org, and generate organization.csv
user-invocable: true
---

# Organization Resolution Skill

Read `output/all_repos.csv`, resolve each repo to its parent organization/owner via GitHub API, deduplicate by organization, and output `output/organizations.csv`.

## Input

- `output/all_repos.csv` — full repo pool (from `/merge-repos`)
- User may optionally specify:
  - A different input CSV path

## Procedure

### Step 1: Run the resolution script

```bash
python3 scripts/resolve_orgs.py output/all_repos.csv --summary -o output/organizations.csv
```

- If exit code is **0** — all owners resolved successfully, go to Step 3.
- If exit code is **1** — some repos have non-GitHub URLs or unparseable URLs that need manual handling, proceed to Step 2.

### Step 2: LLM resolution (fallback for non-GitHub and manual_review items)

For items the script cannot handle (non-GitHub URLs, unparseable URLs), you MUST research each one to find the parent organization.

#### Research methodology

For each `manual_review` or `non_github` item:

1. **Web search** for `"{project_name}" organization` or `"{project_name}" maintained by`
2. **Identify the parent org** — most projects belong to some organization, company, or foundation
3. **If a GitHub org is found**, update the entry with the GitHub org URL and set `owner_type` to `organization` or `user`
4. **If no GitHub org exists**, determine the owner from the project's hosting platform or website
5. **If truly ambiguous**, keep as `manual_review` and flag for the user

#### What to update for each resolved item

| Field | Value |
|-------|-------|
| owner | Organization/owner login or name |
| owner_type | `organization`, `user`, or `manual_review` |
| name | Display name of the org |
| platform | Hosting platform (e.g., `gitlab.com`, `gitee.com`) |
| url | Organization URL |
| source | `LLM解析: {reasoning}` |

After manually resolving items, update `output/organization.csv` with the resolved entries.

### Step 3: Deduplication verification

Verify no duplicate owners exist in the final output:

```bash
awk -F',' 'NR>1 {print tolower($1)}' output/organization.csv | sort | uniq -d
```

If duplicates are found, merge their repo counts and repo lists, keeping the richer metadata entry.

### Step 4: Output summary

Print a summary table:
- Total unique organizations/owners
- Breakdown by type (organization, user, non_github, manual_review)
- Top organizations by repo count
- Any items that could not be resolved

### Step 5: Review with user

Present the resolution results to the user for review. Key things to highlight:
- Owners with many repos — these are the most important organizations
- `user` type owners — may actually be organizations worth investigating
- `non_github` owners — verify their org assignment is correct
- `manual_review` items — need user decision
