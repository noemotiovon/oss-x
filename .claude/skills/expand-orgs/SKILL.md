---
name: expand-orgs
description: Expand organizations from data_classify.csv repos via URL + GitHub API, LLM Web Search for unresolved
user-invocable: true
---

# Org Expansion Skill

For each `entity_type=repo` row in `data_classify.csv`, determine its parent organization.
Script handles URL-based resolution; LLM Web Search fills remaining unknowns with s/a/b/c confidence.

## Input

- `output/data_classify.csv`

## Output

- `output/organizations.csv`

Columns: `org_name, owner, platform, org_url, repo_count, unique_repo_count, repos, source, confidence, reason, description, blog, location`

`unique_repo_count` is the number of distinct upstream URLs among the org's repos (deduped).

Where `source` is one of:
- `url+github_api` — host is github.com and API confirms owner is an Organization
- `url` — host is a known non-GitHub git host (gitee/gitlab/…); owner taken from path
- `pending_llm` — unparseable URL or owner is a personal user account → needs Web Search
- `llm_web_search` — filled in by the LLM step below (with confidence s/a/b/c)

## Procedure

### Step 1: Run the script

```bash
python3 scripts/expand_orgs.py output/data_classify.csv -o output/organizations.csv --summary
```

The script exits 1 if any `pending_llm` rows remain. That's a signal to proceed to step 2, not an error.

### Step 2: Resolve `pending_llm` rows via Web Search

For each row in `output/organizations.csv` where `source == pending_llm`:

1. Read the repo name from `repos` and the original URL from the `reason` text.
2. Use Web Search to find which organization/company actually maintains this project.
   Prefer authoritative sources (official site, GitHub README, Wikipedia, project docs).
3. Update the row fields in-place:
   - `org_name` — canonical org name
   - `org_url` — official org URL (github.com/org if applicable, otherwise homepage)
   - `owner`, `platform` — fill if a GitHub org is found
   - `source` — set to `llm_web_search`
   - `confidence` — one of:
     - `s` — primary source (official docs / GitHub owner) directly states it
     - `a` — multiple independent secondary sources agree
     - `b` — single secondary source or strong inference
     - `c` — weak / ambiguous evidence
   - `reason` — one sentence explaining the conclusion + cite the source URL(s)

If no reliable answer can be found, leave `org_name` blank, set `confidence=c`, and explain in `reason` why it's unresolved. Do NOT guess without evidence.

### Step 3: Summary

Print to the user:
- Total repo rows processed
- URL-resolved org count
- LLM-resolved count (by confidence bucket s/a/b/c)
- Any remaining unresolved rows

## Principles

- Script first, LLM last. Never re-query things the script already resolved.
- Real evidence only. Every LLM conclusion cites a source URL in `reason`.
- Do not mutate `data_classify.csv`.
