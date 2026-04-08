---
name: classify
description: Classify entities from data.csv into repo, organization, foundation, or company
user-invocable: true
---

# Entity Classification Skill

Read `data.csv` and classify each entry into: **repo**, **organization**, **foundation**, **company**.

## Input

CSV file at `data.csv` with columns: `页签,序号,项目名称,分类,上游地址`

User may optionally specify:
- A different CSV path
- `--no-api` to skip GitHub API calls (faster, less accurate)
- Specific rows or 页签 to classify

## Procedure

### Step 1: Run the classification script

```bash
python3 scripts/classify.py data.csv --summary -o output/classified.csv --output-dir output
```

This produces three files:
- `output/classified.csv` — full classification result
- `output/repos.csv` — confirmed repos (input for merge step)
- `output/non_repos.csv` — non-repos (input for step ② LLM classification)

- If exit code is **0** — all items classified, go to Step 3.
- If exit code is **1** — some items marked "unknown", proceed to Step 2.
- If exit code is **2** — error, report to user.

### Step 2: LLM classification (fallback for unknown items)

For items the script cannot classify, you MUST research each item before assigning a category. **Do NOT classify from memory alone** — verify with evidence.

#### Research methodology

For each unknown item, follow this decision tree. Stop at the first conclusive match:

**A. Check if the entry contains multiple independent project URLs**
- If the `上游地址` field lists 2+ URLs pointing to **different** projects (not mirrors of the same project), this is an **organization** — it's a group entry covering multiple repos.
- Example: `openMPI` listing both `open-mpi.org` and `openucx.org` → organization

**B. Check if the URL points to a specific codebase**
- URL has `owner/repo` path pattern (on any git host, SourceForge, Bioconductor, etc.) → likely **repo**
- URL points to a downloadable tarball or specific package page → likely **repo**
- URL is a project-specific domain (e.g., `yambo-code.org`, `openfoam.org`) → likely **repo** (a project can have its own website)

**C. Web search to resolve ambiguity**
Use web search when the URL alone is inconclusive. Search for: `"{project_name}" site:github.com OR site:wikipedia.org`

Key questions to answer:
1. **Is this a single software project, or an umbrella for multiple projects?**
   - Single codebase / single installable package → **repo**
   - Maintains multiple independent repos / sub-projects → **organization**
2. **Is this backed by a registered non-profit?**
   - Has legal entity status as a non-profit / 501(c) → **foundation**
   - Governs open-source projects through formal governance → **foundation**
3. **Is this a for-profit commercial entity?**
   - Sells products/services, has employees, raises funding rounds → **company**

#### Category definitions with verification signals

**repo** — A specific software project / codebase.
- Verification: Can you `git clone` or download ONE specific codebase? Does it produce ONE installable artifact?
- Signals: URL has owner/repo path; project has a single README; installable via `pip install X` / `apt install X` / etc.
- Edge cases:
  - A project with its own domain (e.g., `openfoam.org`) is still a repo if it's ONE codebase
  - A kernel subsystem (KVM, LVS) is a repo — it's a specific code component
  - Bioconductor/CRAN packages are repos — each is a single R package
  - SourceForge projects are repos — each is a single project

**organization** — A group/community maintaining multiple repos, NOT a foundation or company.
- Verification: Does this name refer to a **group** rather than a **single project**? Does it have multiple independent repos?
- Signals: URL points to org-level page (no repo path); entry name ends with "社区"/"community"; entry lists multiple project URLs
- Edge cases:
  - `PyTorch社区` with URL `github.com/pytorch` → organization (org-level URL, community label)
  - A project website listing sub-projects → check if they're independent codebases or modules of one project

**foundation** — A registered non-profit governance body for open-source.
- Verification: Search for `"{name}" foundation non-profit OR 501(c) OR governance`. Confirm legal entity status.
- Signals: Name contains "Foundation"; has formal governance structure; provides neutral home for projects
- Examples: Linux Foundation, CNCF, Apache Software Foundation, Eclipse Foundation, OpenInfra Foundation

**company** — A for-profit commercial entity.
- Verification: Search for `"{name}" company OR Inc OR Ltd OR revenue OR funding`. Confirm commercial status.
- Signals: Sells products/services; has employees and offices; raises VC/PE funding; publicly traded
- Edge cases:
  - A company's open-source GitHub org (e.g., `github.com/meituan`) → **organization** (the parent company relationship is resolved by `/trace-companies`)
  - University labs (e.g., THUDM/清华) → **organization** (institutional parent resolved by `/trace-companies`)

#### Batch research optimization

When multiple unknowns share a pattern, batch them:
- All Bioconductor packages → repo (each is a single R package, verify one to confirm)
- All SourceForge projects → repo (each is a single project)
- All kernel.org URLs → repo (each is a specific kernel component)

Only do individual research for genuinely ambiguous items.

### Step 3: Output

Ensure `output/classified.csv` exists with columns:
`页签,序号,项目名称,分类,上游地址,entity_type,reason`

The `reason` column must indicate the classification source:
- Script-classified: `脚本分类: {evidence}` (auto-filled by script)
- LLM-classified: `LLM分类: {one-line justification with the key signal}`

For items that were in `output/non_repos.csv` and classified by LLM, save the results to `output/non_repos_classified.csv` with the same columns. This file is used by the merge step to extract any entities reclassified as `repo`.

Print a summary table showing counts per category.

### Next steps

After classification is complete, inform the user to run `/merge-repos` to generate `output/all_repos.csv`.

### Step 4: Self-improvement

After classification is complete, review any items where you were uncertain or where the user corrected you. If you discover a new pattern or rule that would help future classifications:

1. **New known entities** — If you identified companies/foundations not in the script's lists (`KNOWN_COMPANIES`, `KNOWN_FOUNDATIONS` in `scripts/classify.py`), add them so the script handles them automatically next time.

2. **New git hosting patterns** — If you found repos on git hosts not in `GIT_HOSTS` (e.g., `code.videolan.org`, `git.kernel.org`), add them to the script's `GIT_HOSTS` set so they're auto-classified.

3. **Edge case lessons** — If the user corrected a classification, update this skill's edge cases documentation above so the same mistake isn't repeated.

Always ask the user before making these improvements.
