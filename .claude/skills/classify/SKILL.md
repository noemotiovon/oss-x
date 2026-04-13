---
name: classify
description: Classify entities from data.csv into repo, organization, or unknown using generic hosting-platform rules + GitHub API
user-invocable: true
---

# Entity Classification Skill (Step ①)

根据 `data.csv` 每行的上游地址，将条目分类为 **repo** / **organization** / **unknown**。

## 输入

`data.csv`（只读，不修改）。至少包含列 `上游地址`，其余列原样透传。

## 输出

`output/data_classify.csv`：原始列 + `entity_type`、`reason`。

## 执行

```bash
python3 scripts/classify.py data.csv -o output/data_classify.csv --summary
```

## 判定规则（通用，不局限 GitHub）

1. 无 URL → `unknown`
2. GitHub：
   - `github.com/{owner}/{repo}[/...]` → `repo`
   - `github.com/{owner}` → 调 `GET /users/{owner}`；`User`/`Organization` 均视为组织根 → `organization`
3. 多租户 Git 平台（`gitlab.*`、`bitbucket.org`、`gitee.com`、`codeberg.org`、`atomgit.com`、`opendev.org`、`salsa.debian.org`、`sourceforge.net`、`framagit.org`、`git.sr.ht`）：
   - `{host}/{owner}/{repo}[/...]` → `repo`
   - `{host}/{owner}` → `organization`
   - SourceForge 额外：`/projects/{name}` 或 `/p/{name}` → `repo`
4. 单项目/专用 Git 服务或归档：
   - URL 以 `.git` 结尾
   - `*.googlesource.com`、`git.*`、`svn.*` 主机
   - `sourceware.org/git/...`、`ftp.gnu.org/gnu/{pkg}`
   - `bioconductor.org/packages/...`、`*.sourceforge.io/net` 项目子域名
   - → `repo`
5. 其他 http(s) URL（项目官网等）→ `repo`

需要 `GITHUB_TOKEN` 环境变量（仅 GitHub 单段路径时用于 API 调用）。

## 校验

- 输出文件 `output/data_classify.csv` 存在且包含 `entity_type`、`reason` 列。
- 打印各类别计数；若仍有 `unknown`，提示运行 `/classify-unknown`。
