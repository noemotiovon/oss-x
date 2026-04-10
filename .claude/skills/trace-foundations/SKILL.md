---
name: trace-foundations
description: Trace foundation affiliation for each repo using script (cache + heuristics) and LLM Web Search for remaining unknowns
user-invocable: true
---

# Foundation Tracing Skill (Step ⑨)

Determine which repos belong to open-source foundations. Uses a 3-layer strategy: cache → heuristics → LLM.

## Input

- `output/repo_exp.csv` — expanded repo list (from step ⑧)

## Procedure

### Step 1: Build foundation project cache (script)

Run the cache builder script to fetch project lists from structured data sources (official APIs and curated lists):

```bash
python3 scripts/build_foundation_cache.py -o output/.cache/foundation_projects.json --summary
```

The script fetches from:
- **Apache**: `projects.apache.org/projects.json` (official JSON API)
- **CNCF**: `landscape.cncf.io/api/items` (Landscape API)
- **Eclipse**: `projects.eclipse.org/api/projects` (Eclipse API)
- **Others**: Curated static lists from official sources (LF, NumFOCUS, OpenJS, PyTorch Foundation, etc.)

To merge new projects with an existing cache (preserving LLM-discovered entries):

```bash
python3 scripts/build_foundation_cache.py --merge -o output/.cache/foundation_projects.json --summary
```

### Step 2: Run the matching script

```bash
python3 scripts/trace_foundations.py output/repo_exp.csv -o output/foundation.csv --summary
```

The script applies 3 layers:
1. **Cache match**: Check each repo against foundation_projects.json (by owner/repo or project name)
2. **Org heuristics**: Map known GitHub orgs to foundations (e.g., `apache/*` → Apache, `kubernetes/*` → CNCF)
3. **Mark unmatched**: Remaining repos are marked `foundation_name=unknown` for LLM processing

### Step 3: LLM Web Search for unmatched repos

For repos still marked `unknown`:

1. **Batch by GitHub org** — repos in the same org likely share the same foundation
2. **Web Search** for each unmatched org/repo: `"{project_name}" foundation OR governance`
3. Determine: which foundation (if any) does this project belong to?
4. Record:
   - `foundation_name` — foundation name, or `none` if not affiliated
   - `evidence` — actual URLs and facts from search
   - `confidence` — S/A/B/C

**IMPORTANT**: If LLM discovers a previously unknown foundation with projects:
1. Add the foundation and its projects to `output/.cache/foundation_projects.json`
2. Consider adding the org mapping to `scripts/trace_foundations.py`'s `ORG_FOUNDATION_MAP`
3. Re-run the script to batch-match remaining repos

### Step 4: Present to user

Show results grouped by foundation:
- Foundation name
- Repos under this foundation
- Evidence and confidence for each

User reviews and may correct assignments. Update `output/foundation.csv` with corrections.

### Step 5: Output summary

Print:
- Total repos processed
- Repos matched by cache / heuristics / LLM
- Repos with foundation affiliation (count by foundation)
- Repos with no foundation (`none`)
- Count by confidence level

### Next step

→ Can run in parallel with `/trace-companies`
