---
name: trace-companies
description: Trace repos/organizations to their parent companies, output companies.csv
user-invocable: true
---

# Company Tracing Skill (Step ④)

Trace each repo/organization to its parent company using known mappings, LLM research, and human confirmation.

## Input

- `output/all_repos.csv` — full repo pool (from merge step)
- `output/organizations.csv` — verified organizations (from step ③)

## Procedure

### Step 1: Run the prep script

```bash
python3 scripts/trace_companies.py output/all_repos.csv output/organizations.csv \
    --summary -o output/companies_candidates.csv
```

- If exit code is **0** — all owners have known company mappings, go to Step 3.
- If exit code is **1** — some owners need LLM research, proceed to Step 2.

### Step 2: LLM research for unknown company affiliations

For each row in `output/companies_candidates.csv` where `confidence=unknown`, research the company affiliation.

#### Research methodology

For each unknown owner/org:

1. **Check the org's GitHub page metadata** — description, blog URL, and location often reveal the company
2. **Web search** for `"{org_name}" company OR Inc OR Ltd OR "backed by" OR "founded by"`
3. **Check the blog/website URL** — commercial domains often point to the parent company

#### Decision criteria

- **Has parent company**: The org is owned/maintained by a for-profit company
  - Set `company` to the company name, `confidence` to `high`, `source` to `LLM研究: {evidence}`
- **Is an independent project**: Community-driven, no single corporate owner
  - Set `company` to empty, `confidence` to `none`, `source` to `LLM研究: 独立社区项目`
- **Ambiguous**: Multiple corporate sponsors or unclear ownership
  - Set `company` to best guess, `confidence` to `low`, `source` to `LLM研究: {details}`

#### Batch optimization

Group unknowns by pattern:
- All orgs under the same parent (e.g., multiple Google orgs) — research once, apply to all
- University/research labs — often not companies, mark as `none` unless they have a commercial arm
- Chinese tech orgs — check if they belong to BAT/华为/字节 etc.

After research, update `output/companies_candidates.csv` with findings.

### Step 3: Generate companies.csv

From the completed candidates file, produce the final deduplicated company list.

**Present candidates to the user for review** before generating the final file. Group by company and show:
- Company name
- Associated orgs/repos
- Evidence/source

After user confirmation, generate `output/companies.csv` with columns:

```
company,url,associated_orgs,associated_repos,evidence
```

Where:
- `company` — Company name
- `url` — Company website or primary URL
- `associated_orgs` — Semicolon-joined list of GitHub orgs belonging to this company
- `associated_repos` — Semicolon-joined list of key repos
- `evidence` — How the affiliation was determined

Deduplicate by company name (case-insensitive).

### Step 4: Self-improvement

If you identified new company → org mappings, add them to `KNOWN_COMPANIES` in `scripts/trace_companies.py` so future runs auto-classify them. Ask the user before making changes.
