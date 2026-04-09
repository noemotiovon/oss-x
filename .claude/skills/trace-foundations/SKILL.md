---
name: trace-foundations
description: Use LLM Web Search to determine foundation affiliation for each repo
user-invocable: true
---

# Foundation Tracing Skill (Step ⑨)

Determine which repos belong to open-source foundations. Uses a 3-layer strategy: cache → heuristics → LLM.

## Input

- `output/repo_exp.csv` — expanded repo list (from step ⑧)

## Procedure

### Step 1: Build foundation project cache (LLM Web Search)

For each major foundation, **use Web Search** to find their complete project list. Save results to `output/.cache/foundation_projects.json`.

Search each foundation's official project list:

| Foundation | Search Query |
|-----------|-------------|
| Apache Software Foundation | `site:projects.apache.org list` |
| CNCF | `CNCF projects landscape graduated incubating sandbox` |
| Linux Foundation | `Linux Foundation projects list` |
| LF AI & Data | `LF AI Data Foundation projects` |
| Eclipse Foundation | `Eclipse Foundation projects list` |
| OpenJS Foundation | `OpenJS Foundation projects list` |
| OpenInfra Foundation | `OpenInfra Foundation projects` |
| Python Software Foundation | `Python Software Foundation projects` |
| Rust Foundation | `Rust Foundation members projects` |
| NumFOCUS | `NumFOCUS sponsored projects list` |
| GNOME Foundation | `GNOME Foundation projects` |
| Mozilla Foundation | `Mozilla Foundation projects` |
| Blender Foundation | `Blender Foundation projects` |
| OpenCV Foundation | `OpenCV Foundation projects` |

For each foundation, record in the cache:
```json
{
  "Foundation Name": {
    "projects": ["owner/repo", "owner/repo2", ...],
    "evidence": "source URL where project list was found"
  }
}
```

Save cache to `output/.cache/foundation_projects.json`.

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

**IMPORTANT**: If LLM discovers a previously unknown large foundation with many projects:
1. Add the foundation and its projects to `output/.cache/foundation_projects.json`
2. Add the org mapping to `scripts/trace_foundations.py`'s `ORG_FOUNDATION_MAP`
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
