# OSS-X: Open Source Ecosystem Discovery Pipeline

OSS-X is an AI-assisted pipeline that takes a seed list of open-source projects and systematically discovers the full ecosystem around them — tracing each project **upward** to its parent organizations, companies, and foundations, then **expanding downward** to find popular sibling projects.

## How It Works

The pipeline combines four roles:

| Role | Responsibility |
|------|---------------|
| **Python scripts** | Deterministic logic: URL parsing, CSV merging/splitting, deduplication |
| **GitHub API** | Verify repos/orgs, fetch owner info, query org statistics |
| **LLM (Claude Code Web Search)** | Research ambiguous cases with real web data — no guessing allowed |
| **Human** | Final confirmation on all LLM judgments |

Every LLM judgment includes a **confidence level** (S/A/B/C) and **evidence** from web search results.

## Prerequisites

- **Python 3.10+**
- **`GITHUB_TOKEN`** environment variable (required for GitHub API)
- **Claude Code** (to run `/skill` commands)

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

## Input Format

Place your seed data in `data.csv` at the project root:

```csv
页签,序号,项目名称,*分类,*上游地址
昇腾,1,transformers,训练加速,https://github.com/huggingface/transformers
```

## Pipeline Steps

```
data.csv
  │
  ▼
① /classify ──────────► classified.csv          (GitHub API + script)
  │
  ▼
② /classify-unknown ──► unknown.csv             (LLM + human)
  │
  ▼
③ /split-merge ───────► repo.csv                (script)
                       ► organization.csv
  │
  ▼
④ /resolve-orgs ──────► repo_known_org.csv      (GitHub API + script)
                       ► repo_unknown_org.csv
  │
  ▼
⑤ /resolve-unknown-orgs ► repo_unknown_org.csv  (LLM + human)
  │
  ▼
⑥ /merge-orgs ────────► org_exp.csv             (script)
  │
  ▼
⑦ /validate-orgs ─────► org_exp_val.csv         (script + GitHub API + LLM + human)
  │
  ▼
⑧ /expand-repos ──────► repo_exp.csv            (GitHub API + LLM + human)
  │
  ├─────────────────────────┐
  ▼                         ▼
⑨ /trace-foundations      ⑩ /trace-companies
  ► foundation.csv          ► company.csv
  (LLM + human)             (LLM + human)
```

### Step ① — Classify (`/classify`)

Classify each entry using GitHub API: **repo**, **organization**, or **unknown**.

```bash
python3 scripts/classify.py data.csv -o output/classified.csv
```

- Parses URLs and calls GitHub API to verify type
- **Output**: `output/classified.csv`

### Step ② — Classify Unknown (`/classify-unknown`)

Use LLM Web Search to classify items the API couldn't resolve.

- LLM provides: type judgment, evidence, confidence (S/A/B/C)
- Human reviews and corrects
- **Output**: `output/unknown.csv`

### Step ③ — Split & Merge (`/split-merge`)

Split classified + unknown results by type into separate files.

```bash
python3 scripts/split_merge.py output/classified.csv output/unknown.csv -o output
```

- **Output**: `output/repo.csv`, `output/organization.csv`

### Step ④ — Resolve Repo Organizations (`/resolve-orgs`)

Query GitHub API to find which organization each repo belongs to.

```bash
python3 scripts/resolve_orgs.py output/repo.csv -o output
```

- Known orgs: aggregate repos by org → `repo_known_org.csv`
- Unknown orgs: keep as-is → `repo_unknown_org.csv`
- **Output**: `output/repo_known_org.csv`, `output/repo_unknown_org.csv`

### Step ⑤ — Resolve Unknown Orgs (`/resolve-unknown-orgs`)

Use LLM Web Search to find org info for repos without GitHub org.

- LLM provides: org name, evidence, confidence (S/A/B/C)
- Human reviews and corrects
- **Output**: `output/repo_unknown_org.csv` (updated with org info)

### Step ⑥ — Merge Organizations (`/merge-orgs`)

Merge all organization sources and deduplicate.

```bash
python3 scripts/merge_orgs.py output/organization.csv output/repo_known_org.csv output/repo_unknown_org.csv -o output/org_exp.csv
```

- **Output**: `output/org_exp.csv`

### Step ⑦ — Validate Organizations (`/validate-orgs`)

Determine whether each organization is a valid, meaningful open-source org.

```bash
python3 scripts/validate_orgs.py output/org_exp.csv -o output/org_exp_val.csv
```

- Auto-valid if repo count > 1
- GitHub API: check total repos, star>100 count, active count → human decides
- LLM Web Search for non-GitHub orgs → human decides
- **Output**: `output/org_exp_val.csv`

### Step ⑧ — Expand Repos (`/expand-repos`)

Discover popular and active repos from original organizations (`organization.csv`).

```bash
python3 scripts/expand_repos.py output/repo.csv output/organization.csv -o output/repo_exp.csv
```

- GitHub API: fetch repos with **stars > 100 AND active in last year** from original orgs
- LLM Web Search: find popular repos for non-GitHub orgs
- Tags each row with `source` (repo / org_expansion)
- **Output**: `output/repo_exp.csv`

### Step ⑨ — Trace Foundations (`/trace-foundations`)

Determine foundation affiliation using a 3-layer strategy: cache → heuristics → LLM.

```bash
python3 scripts/trace_foundations.py output/repo_exp.csv -o output/foundation.csv
```

1. **Build cache**: LLM searches each major foundation's project list → `output/.cache/foundation_projects.json`
2. **Script match**: Match repos against cache + built-in org→foundation mapping
3. **LLM fallback**: Web Search for unmatched repos; if new large foundations found, update cache and re-run
- All LLM results include confidence (S/A/B/C) and require human review
- **Output**: `output/foundation.csv`

### Step ⑩ — Trace Companies (`/trace-companies`)

Use LLM Web Search to determine company affiliation for each repo.

- Provides: company name, evidence, confidence (S/A/B/C)
- `unknown` if not affiliated
- **Output**: `output/company.csv`

> Steps ⑨ and ⑩ can run in parallel — they both read from `output/repo_exp.csv`.

## Confidence Levels

All LLM judgments include a confidence rating:

| Level | Meaning |
|-------|---------|
| **S** | Certain — clear official source |
| **A** | High confidence — multiple reliable sources |
| **B** | Medium confidence — partial or less authoritative sources |
| **C** | Low confidence — based on indirect information |

## Recommended Execution Order

**Phase 1 — Classification**
1. `/classify` — API-based classification
2. `/classify-unknown` — LLM + human review for unknowns
3. `/split-merge` — Split into repo.csv and organization.csv

**Phase 2 — Organization Resolution**
4. `/resolve-orgs` — GitHub API org lookup
5. `/resolve-unknown-orgs` — LLM + human review for unknown orgs
6. `/merge-orgs` — Merge all org sources

**Phase 3 — Validation & Expansion**
7. `/validate-orgs` — Validate org effectiveness
8. `/expand-repos` — Expand repos from valid orgs

**Phase 4 — Tracing (can run in parallel)**
9. `/trace-foundations` — Find foundation affiliations
10. `/trace-companies` — Find company affiliations

## Project Structure

```
├── data.csv                 # Seed input data
├── CLAUDE.md                # Project context for Claude
├── design.md                # Detailed implementation guide (Chinese)
├── scripts/
│   ├── classify.py          # Step ① — GitHub API classification
│   ├── split_merge.py       # Step ③ — Split by type
│   ├── resolve_orgs.py      # Step ④ — Resolve repo orgs
│   ├── merge_orgs.py        # Step ⑥ — Merge organizations
│   ├── validate_orgs.py     # Step ⑦ — Validate organizations
│   └── expand_repos.py      # Step ⑧ — Expand repos
├── .claude/skills/
│   ├── classify/            # Step ①
│   ├── classify-unknown/    # Step ②
│   ├── split-merge/         # Step ③
│   ├── resolve-orgs/        # Step ④
│   ├── resolve-unknown-orgs/# Step ⑤
│   ├── merge-orgs/          # Step ⑥
│   ├── validate-orgs/       # Step ⑦
│   ├── expand-repos/        # Step ⑧
│   ├── trace-foundations/    # Step ⑨
│   └── trace-companies/     # Step ⑩
└── output/                  # All generated CSV files
```

## Design Principles

- **Single responsibility**: Each step does one thing with clear inputs and outputs
- **Real data only**: LLM must use Web Search for real information — no guessing or hallucinating
- **Confidence tracking**: All LLM judgments include S/A/B/C confidence levels with evidence
- **Human in the loop**: All LLM outputs require human verification
- **No data mutation**: Each step reads upstream files and writes new files; never modifies originals
- **Continuous improvement**: Patterns discovered during runs should be codified into scripts
