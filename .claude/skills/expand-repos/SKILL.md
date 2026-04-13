---
name: expand-repos
description: Expand repos from orgs in data_classify.csv using GitHub API + scoring (top 20 per org)
user-invocable: true
---

# Repo Expansion Skill

Starting from `output/data_classify.csv`, expand organizations into their top repos and merge with the original repos.

## Input

- `output/data_classify.csv` — must contain `entity_type` column (`repo` / `organization` / `unknown`) and `上游地址`.

## Output

- `output/repos.csv` — merged list of original repos + top-N repos per org (deduplicated, originals win on collision).

## Procedure

### Step 1: Run the expansion script

```bash
python3 scripts/expand_repos.py output/data_classify.csv \
    -o output/repos.csv --top 20 --summary
```

Requires `GITHUB_TOKEN` env var.

### Scoring formula

For each repo under a GitHub org, the script fetches `stars`, `forks`, `pushed_at` via `/orgs/{login}/repos` (falls back to `/users/{login}/repos`) and scores:

```
score = 2 * log10(stars + 1)
      + 1 * log10(forks + 1)
      + 3 * exp(-days_since_last_push / 180)
```

- Log terms keep popularity on a comparable scale across orders of magnitude.
- The recency term (half-life ~125d) rewards actively pushed projects; stale repos decay toward 0.

Forks and archived repos are excluded. Top `--top` (default 20) repos per org are kept.

### Step 2: Merge & dedupe

- All `entity_type=repo` rows from `data_classify.csv` are emitted first with `source=repo`.
- Expanded rows are emitted with `source=org_expansion` and their `score`, `stars`, `forks`, `pushed_at`, `expanded_from_org`.
- URL-normalized dedup: if an expanded repo already exists as an original, the original wins.

### Output columns

`页签, 序号, 项目名称, 分类, 上游地址, entity_type, source, expanded_from_org, stars, forks, pushed_at, score, language, description, reason`

### Caching

Org repo listings are cached in `output/.cache/org_repos_expansion_cache.json`. Use `--no-cache` to force refresh.

### Next step

→ `/trace-foundations` and `/trace-companies` (parallel)
