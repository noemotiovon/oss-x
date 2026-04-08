# OSS-X: Open Source Ecosystem Discovery Pipeline

OSS-X is an AI-assisted pipeline that takes a seed list of open-source projects and systematically discovers the full ecosystem around them — tracing each project **upward** to its parent organizations, companies, and foundations, then **expanding downward** to find popular sibling projects. The final output is a unified table cross-referencing repos, organizations, companies, and foundations.

## How It Works

The pipeline combines three roles at each step:

| Role | Responsibility |
|------|---------------|
| **Python scripts** | Deterministic logic: URL parsing, GitHub API calls, deduplication, merging |
| **LLM (Claude)** | Handles ambiguous cases the scripts can't resolve: web research, classification, entity tracing |
| **Human** | Final confirmation on key decisions: entity types, org validity, company/foundation affiliations |

Each step follows the same pattern: **script auto-classifies what it can → LLM handles unknowns → human confirms**.

## Prerequisites

- **Python 3.10+**
- **`GITHUB_TOKEN`** environment variable (recommended to avoid GitHub API rate limits)
- **Claude Code** or **Cursor** with Claude agent mode (to run the `/skill` commands)

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

## Input Format

Place your seed data in `data.csv` at the project root:

```csv
页签,序号,项目名称,分类,上游地址
昇腾,1,transformers,训练加速,https://github.com/huggingface/transformers
昇腾,2,accelerate,训练加速,https://github.com/huggingface/accelerate
```

| Column | Description |
|--------|-------------|
| 页签 | Source tab/category group |
| 序号 | Row number within the tab |
| 项目名称 | Project name |
| 分类 | Sub-category (e.g., 训练加速, 推理加速) |
| 上游地址 | Upstream URL (typically GitHub) |

## Pipeline Steps

```
data.csv
  │
  ▼
① /classify ──────────────► classified.csv, repos.csv, non_repos.csv
  │
  ▼
② /merge-repos ───────────► all_repos.csv
  │
  ├─► ③ /resolve-orgs ───► organizations.csv
  ├─► ④ /trace-companies ► companies.csv
  ├─► ⑤ /trace-foundations ► foundations.csv
  │
  ▼
⑥ /expand-orgs ──────────► org_expanded_repos.csv
  │
  ▼
⑦ /expand-foundations ────► foundations_deduped.csv + foundation_expanded_repos.csv
  │
  ▼
⑧ /merge-final ──────────► final.csv
```

### Step ① — Classify (`/classify`)

Classify each entry in `data.csv` as **repo**, **organization**, **foundation**, or **company**.

```bash
# Runs automatically via the skill:
python3 scripts/classify.py data.csv --summary -o output/classified.csv --output-dir output
```

- The script parses URLs and uses the GitHub API to verify repos
- Items it can't classify are marked `unknown` for LLM research
- **Output**: `output/classified.csv`, `output/repos.csv`, `output/non_repos.csv`

### Step ② — Merge Repos (`/merge-repos`)

Merge confirmed repos from Step ① with any items reclassified as `repo` by the LLM.

```bash
python3 scripts/merge_repos.py output/repos.csv output/non_repos_classified.csv \
    -o output/all_repos.csv --summary
```

- **Output**: `output/all_repos.csv` — the full repo pool used by all subsequent steps

### Step ③ — Resolve Organizations (`/resolve-orgs`)

Resolve each repo to its parent GitHub organization/owner.

```bash
python3 scripts/resolve_orgs.py output/all_repos.csv --summary -o output/organizations.csv
```

- Uses GitHub API to determine `owner` and `owner.type`
- LLM handles non-GitHub URLs and ambiguous cases
- Human verifies org validity (filters out personal namespaces, abandoned orgs)
- **Output**: `output/organizations.csv`

### Step ④ — Trace Companies (`/trace-companies`)

Determine which repos/organizations are backed by commercial companies.

```bash
python3 scripts/trace_companies.py output/all_repos.csv output/organizations.csv \
    --summary -o output/companies_candidates.csv
```

- Known company mappings are applied automatically
- LLM researches unknown affiliations via web search
- Human confirms company assignments
- **Output**: `output/companies.csv`

### Step ⑤ — Trace Foundations (`/trace-foundations`)

Determine which repos/organizations belong to open-source foundations.

```bash
python3 scripts/trace_foundations.py output/all_repos.csv output/organizations.csv \
    --summary -o output/foundations_candidates.csv
```

- Checks CNCF, Apache, Linux Foundation, Eclipse, OpenJS, etc.
- LLM researches unknown affiliations
- Human confirms foundation assignments
- **Output**: `output/foundations.csv`

> Steps ③④⑤ can run in parallel — they all read from `output/all_repos.csv`.

### Step ⑥ — Expand Organizations (`/expand-orgs`)

For each verified organization, discover their other popular repos.

```bash
python3 scripts/expand_orgs.py output/organizations.csv \
    --existing output/all_repos.csv --summary -o output/org_expanded_repos.csv
```

- Fetches org repos via GitHub API, filtered by stars and activity
- Human reviews candidate repos for relevance
- **Output**: `output/org_expanded_repos.csv`

### Step ⑦ — Expand Foundations (`/expand-foundations`)

Deduplicate foundations, then discover their notable projects.

```bash
python3 scripts/dedup_foundations.py output/foundations.csv \
    -o output/foundations_deduped.csv --summary
```

- LLM researches each foundation's project portfolio
- Human reviews candidate projects
- **Output**: `output/foundations_deduped.csv`, `output/foundation_expanded_repos.csv`

### Step ⑧ — Final Merge (`/merge-final`)

Merge all pipeline outputs into a single unified table.

```bash
python3 scripts/merge_final.py -o output/final.csv --summary
```

- Deduplicates by URL, cross-references repos with orgs/companies/foundations
- **Output**: `output/final.csv`

## Usage Guide

### Running with Claude Code

In Claude Code, invoke each skill as a slash command:

```
/classify
/merge-repos
/resolve-orgs
/trace-companies
/trace-foundations
/expand-orgs
/expand-foundations
/merge-final
```

### Running with Cursor

In Cursor with agent mode, reference the skill name in your prompt. For example:

```
Please run the /classify skill on data.csv
```

or

```
Please run /merge-repos to generate all_repos.csv
```

Cursor will read the corresponding skill file from `.claude/skills/` and execute the procedure.

### Recommended Execution Order

**Phase 1 — Classification**
1. `/classify` — Classify all entries
2. Review `output/non_repos.csv`, confirm LLM classifications
3. `/merge-repos` — Generate the full repo pool

**Phase 2 — Tracing (can run in parallel)**
4. `/resolve-orgs` — Find parent organizations
5. `/trace-companies` — Find parent companies
6. `/trace-foundations` — Find parent foundations

**Phase 3 — Expansion**
7. `/expand-orgs` — Discover popular repos from each org
8. `/expand-foundations` — Discover notable projects from each foundation

**Phase 4 — Assembly**
9. `/merge-final` — Produce the final unified table

## Output Schema

The final output `output/final.csv` contains:

| Column | Description |
|--------|-------------|
| `name` | Entity name |
| `url` | Standardized URL |
| `type` | `repo` / `organization` / `company` / `foundation` |
| `category` | Original sub-category (e.g., 训练加速) |
| `organization` | Parent GitHub organization |
| `company` | Parent company (may be empty) |
| `foundation` | Parent foundation (may be empty) |
| `stars` | GitHub stars (repos only) |
| `last_active` | Last push date (repos only) |
| `description` | Entity description |
| `evidence` | Source/evidence for classifications |

## File Dependency Map

```
data.csv
  → output/classified.csv              (Step ①)
  → output/repos.csv                   (Step ①)
  → output/non_repos.csv               (Step ①)
     → output/non_repos_classified.csv  (Step ① LLM fallback)
  → output/all_repos.csv               (Step ②)
     → output/organizations.csv        (Step ③)
     → output/companies.csv            (Step ④)
     → output/foundations.csv           (Step ⑤)
     → output/org_expanded_repos.csv   (Step ⑥)
     → output/foundations_deduped.csv   (Step ⑦)
     → output/foundation_expanded_repos.csv (Step ⑦)
  → output/final.csv                   (Step ⑧)
```

## Design Principles

- **Waterfall strategy**: Script handles deterministic cases → LLM handles ambiguous cases → human confirms
- **Known-entity lookup**: Curated lists in scripts (`KNOWN_COMPANIES`, `KNOWN_FOUNDATIONS`) enable instant classification without API calls
- **Continuous improvement**: When the LLM discovers new patterns or entities, it updates the scripts' known lists so future runs are faster and more accurate
- **No data mutation**: Each step reads upstream files and writes new files; original input is never modified

## Project Structure

```
├── data.csv                 # Seed input data
├── CLAUDE.md                # Project context for Claude
├── design.md                # Detailed implementation guide (Chinese)
├── scripts/
│   ├── classify.py          # Step ① — Entity classification
│   ├── merge_repos.py       # Step ② — Merge repo sources
│   ├── resolve_orgs.py      # Step ③ — Resolve organizations
│   ├── trace_companies.py   # Step ④ — Trace companies
│   ├── trace_foundations.py  # Step ⑤ — Trace foundations
│   ├── expand_orgs.py       # Step ⑥ — Expand org repos
│   ├── dedup_foundations.py  # Step ⑦ — Dedup & expand foundations
│   └── merge_final.py       # Step ⑧ — Final merge
├── .claude/skills/
│   ├── classify/SKILL.md
│   ├── merge-repos/SKILL.md
│   ├── resolve-orgs/SKILL.md
│   ├── trace-companies/SKILL.md
│   ├── trace-foundations/SKILL.md
│   ├── expand-orgs/SKILL.md
│   ├── expand-foundations/SKILL.md
│   └── merge-final/SKILL.md
└── output/                  # All generated CSV files
```
