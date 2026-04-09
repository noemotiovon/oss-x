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
data.csv → ① /classify → ② /classify-unknown → ③ /split-merge
         → ④ /resolve-orgs → ⑤ /resolve-unknown-orgs → ⑥ /merge-orgs
         → ⑦ /validate-orgs → ⑧ /expand-repos
         → ⑨ /trace-foundations  (parallel)
         → ⑩ /trace-companies   (parallel)
```

| Step | Skill | Script | Input → Output |
|------|-------|--------|----------------|
| ① 输入分类 | `/classify` | `scripts/classify.py` | `data.csv` → `classified.csv` |
| ② Unknown 分类 | `/classify-unknown` | — | `classified.csv` → `unknown.csv` |
| ③ 拆分合并 | `/split-merge` | `scripts/split_merge.py` | `classified.csv` + `unknown.csv` → `repo.csv`, `organization.csv` |
| ④ Repo 溯源组织 | `/resolve-orgs` | `scripts/resolve_orgs.py` | `repo.csv` → `repo_known_org.csv`, `repo_unknown_org.csv` |
| ⑤ Unknown Org 补全 | `/resolve-unknown-orgs` | — | `repo_unknown_org.csv` → `repo_unknown_org.csv`(更新) |
| ⑥ 组织合并去重 | `/merge-orgs` | `scripts/merge_orgs.py` | `organization.csv` + `repo_known_org.csv` + `repo_unknown_org.csv` → `org_exp.csv` |
| ⑦ 组织有效性验证 | `/validate-orgs` | `scripts/validate_orgs.py` | `org_exp.csv` → `org_exp_val.csv` |
| ⑧ Repo 扩展 | `/expand-repos` | `scripts/expand_repos.py` | `repo.csv` + `organization.csv` → `repo_exp.csv` |
| ⑨ 溯源基金会 | `/trace-foundations` | `scripts/trace_foundations.py` | `repo_exp.csv` → `foundation.csv` |
| ⑩ 溯源公司 | `/trace-companies` | — | `repo_exp.csv` → `company.csv` |

## Key Design Principles

- **Single responsibility**: Each step does one thing with clear inputs and outputs
- **Real data only**: LLM uses Web Search for real information, no guessing
- **Confidence tracking**: LLM judgments include S/A/B/C confidence with evidence
- **Human in the loop**: All LLM outputs require human verification
- **No data mutation**: Each step reads upstream files and generates new files; never modifies original CSV

## Requirements

- `GITHUB_TOKEN` env var for GitHub API access (required)
- Python 3.10+
