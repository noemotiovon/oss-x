# OSS-X: Open Source Project Insight

This project provides methodology and tools for gathering insights about open-source projects, organizations, foundations, and companies.

## Project Structure

```
scripts/        — Python scripts for deterministic logic
.claude/skills/ — Claude Code skill files (.md)
output/         — Pipeline output files (CSV)
```

## Pipeline Overview

```
data.csv → ① /classify → ② /merge-repos → ③ /resolve-orgs → ⑥ /expand-orgs
                                          → ④ /trace-companies
                                          → ⑤ /trace-foundations → ⑦ /expand-foundations
                                          → ⑧ /merge-final
```

| Step | Skill | Script | Input → Output |
|------|-------|--------|----------------|
| ① 输入分类 | `/classify` | `scripts/classify.py` | `data.csv` → `classified.csv`, `repos.csv`, `non_repos.csv` |
| ② 合并 Repo 池 | `/merge-repos` | `scripts/merge_repos.py` | `repos.csv` + `non_repos_classified.csv` → `all_repos.csv` |
| ③ 溯源组织 | `/resolve-orgs` | `scripts/resolve_orgs.py` | `all_repos.csv` → `organizations.csv` |
| ④ 溯源公司 | `/trace-companies` | `scripts/trace_companies.py` | `all_repos.csv` + `organizations.csv` → `companies.csv` |
| ⑤ 溯源基金会 | `/trace-foundations` | `scripts/trace_foundations.py` | `all_repos.csv` + `organizations.csv` → `foundations.csv` |
| ⑥ 组织扩展 | `/expand-orgs` | `scripts/expand_orgs.py` | `organizations.csv` → `org_expanded_repos.csv` |
| ⑦ 基金会扩展 | `/expand-foundations` | `scripts/dedup_foundations.py` | `foundations.csv` → `foundations_deduped.csv` + `foundation_expanded_repos.csv` |
| ⑧ 最终整合 | `/merge-final` | `scripts/merge_final.py` | all outputs → `final.csv` |

## Key Design Principles

- **Waterfall strategy**: Script auto-classifies what it can → LLM handles unknowns → human confirms
- **Known-entity lookup**: Curated lists in scripts (`KNOWN_COMPANIES`, `KNOWN_FOUNDATIONS`) for instant classification
- **Continuous improvement**: When LLM discovers new patterns, update the scripts' known lists
- **No data mutation**: Each step reads upstream files and generates new files; never modifies original CSV

## Requirements

- `GITHUB_TOKEN` env var for GitHub API access (optional but recommended to avoid rate limits)
- Python 3.10+
