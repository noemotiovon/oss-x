# Open Source 生态发现流水线 — 实现指南

## 一、背景

我们有一批待分析的开源项目/实体（data.csv，约 660 条），目标是：以这批种子数据为起点，**向上溯源**找到所属的组织、公司、基金会，再**向下扩展**发现热门项目，最终输出一张包含 repo、organization、company、foundation 及佐证信息的完整大表。

整个流程为**单向线性流水线**（无循环），涉及 **脚本自动化**、**LLM 辅助判断**、**人工确认** 三种角色的配合。所有步骤只读取上游文件、生成新文件，**不修改原始 CSV**。

---

## 二、输入格式

`data.csv`，每行代表一个待分析的实体：

```csv
页签,序号,项目名称,分类,上游地址
昇腾,1,transformers,训练加速,https://github.com/huggingface/transformers
```

---

## 三、流程总览

```
data.csv
  │
  ▼
┌──────────────────────────────┐
│ ① 输入分类                    │  → output/classified.csv
│   脚本判断：repo vs 非 repo   │  → output/repos.csv  +  output/non_repos.csv
└──────┬──────────────┬────────┘
       │ repo          │ 非 repo
       ▼               ▼
   repos.csv  ┌────────────────────────────┐
       ▲      │ ② LLM 数据收集 + 人工分类    │  → output/non_repos_classified.csv
       │      │   · LLM 提供事实佐证          │
       │      │   · 人工最终分类               │
       │      │   · 分类结果可能为 repo        │
       │      └──────┬─────────────────────┘
       │◄── repo ────┘
       │
       ▼
┌──────────────────────────────┐
│ 合并：全量 Repo 池             │  → output/all_repos.csv
└──────┬───────────────────────┘
       │
       ├──────────────────────────────────┬──────────────────────┐
       ▼                                  ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────┐
│ ③ 溯源组织         │  │ ④ 溯源公司        │  │ ⑤ 溯源基金会         │
│  organization      │  │  company          │  │  foundation          │
│  (GitHub API       │  │  (LLM + 人工)     │  │  (LLM + 人工)        │
│   + LLM + 人工验证) │  │                   │  │                      │
└──────┬────────────┘  └──────┬───────────┘  └──────┬──────────────┘
       │                      │                      │
       ▼                      ▼                      ▼
  output/                output/                output/
  organizations.csv      companies.csv          foundations.csv
  (已验证有效)
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ ⑥ Organization 向下扩展热门项目（脚本 + 人工审核）              │
│   → output/org_expanded_repos.csv                            │
└──────┬───────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ ⑦ Foundation 去重 + 向下扩展热门项目                           │
│   → output/foundations_deduped.csv                            │
│   → output/foundation_expanded_repos.csv                     │
└──────┬───────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ ⑧ 最终整合                                                    │
│   → output/final.csv                                          │
└──────────────────────────────────────────────────────────────┘
```

---

## 四、各步骤详细说明

### 步骤 ① — 输入分类（脚本自动化）

**目的**：快速将输入分为 repo 和非 repo 两类。

**输入**：`data.csv`

**实现方式**：
- 解析 URL，若符合 `github.com/{owner}/{repo}` 格式，调用 GitHub API (`GET /repos/{owner}/{repo}`) 验证
- API 返回成功 → 确认为 repo
- API 返回 404、URL 不含 repo 名、或非 GitHub URL → 标记为「非 repo」

**对应模块**：`scripts/classify.py` + `/classify` skill

**输出**：
- `output/classified.csv` — 全量分类结果（含 `type` 字段）
- `output/repos.csv` — 确认为 repo 的子集
- `output/non_repos.csv` — 非 repo 的子集，待步骤 ② 处理

---

### 步骤 ② — LLM 数据收集 + 人工分类

**目的**：对非 repo 实体进行信息收集和分类。

**输入**：`output/non_repos.csv`

**LLM 职责**（不做最终决策）：
- 给出实体的**事实性陈述**（成立时间、主要项目、隶属关系等）
- 提供**佐证链接**（官网、Wikipedia、GitHub org 页面等）
- 建议分类为 `repo` / `organization` / `foundation` / `company`，附置信度

**人工职责**：
- 根据 LLM 信息做最终分类
- 若分类结果为 repo，则在下一步合并入 Repo 池

**输出**：`output/non_repos_classified.csv` — 每条记录含人工确认的 `type` 字段及 LLM 佐证信息

---

### 合并步骤 — 生成全量 Repo 池

**输入**：
- `output/repos.csv`（步骤 ① 产出）
- `output/non_repos_classified.csv` 中 `type=repo` 的记录（步骤 ② 产出）

**输出**：`output/all_repos.csv` — 全量 repo 列表，后续步骤 ③④⑤ 的统一输入

---

### 步骤 ③ — 由 Repo 溯源 Organization（脚本 + LLM + 人工）

**目的**：从全量 Repo 出发，向上找到每个 repo 所属的 GitHub 组织，并验证组织的有效性。

**输入**：`output/all_repos.csv`

**实现方式**：
1. **脚本**：通过 GitHub API 获取 repo 的 `owner` 信息，判断 `owner.type` 是否为 `Organization`，提取 org URL（如 `github.com/huggingface`）
2. **脚本**：去重后，对每个 org 调用 GitHub API 获取公开 repo 数、成员数、简介等基本信息作为佐证
3. **LLM**：对非 GitHub repo 或归属不明确的情况，搜索并给出建议；对每个 org 提供活跃度、代表性项目等补充佐证
4. **人工**：根据佐证信息判断该 org 是否为有效组织（排除个人命名空间、废弃组织等）

> **为什么需要人工验证**：GitHub 上 `owner.type=Organization` 只代表账号类型，不代表是有意义的组织。个人也可创建 org 作为命名空间，这类 org 不应进入后续扩展。

**对应模块**：`scripts/resolve_orgs.py` + `/resolve-orgs` skill

**输出**：`output/organizations.csv` — 人工验证后的有效组织列表，每行含 org 名称、URL、关联的 repo 列表、佐证信息

---

### 步骤 ④ — 由 Repo 溯源 Company（LLM + 人工）

**目的**：判断每个 repo / organization 背后是否有商业公司。

**输入**：`output/all_repos.csv` + `output/organizations.csv`

**实现方式**：
- **LLM**：基于知识库 + Web 搜索，判断 repo 或其所属 org 是否隶属于某公司
- **人工**：确认公司归属（部分 repo 可能不属于任何公司）

**输出**：`output/companies.csv` — 去重后的公司列表，每行含公司名称、URL、关联的 repo/org 列表、佐证信息

> 注意：不是所有 repo 都属于公司，允许为空。

---

### 步骤 ⑤ — 由 Repo 溯源 Foundation（LLM + 人工）

**目的**：判断每个 repo 是否隶属于某个开源基金会。

**输入**：`output/all_repos.csv` + `output/organizations.csv`

**实现方式**：
- **LLM**：基于知识库 + Web 搜索，判断 repo 是否为某基金会旗下项目
- **人工**：确认基金会归属（部分 repo 可能不属于任何基金会）

**输出**：`output/foundations.csv` — 去重后的基金会列表，每行含基金会名称、URL、关联的 repo 列表、佐证信息

> 注意：不是所有 repo 都属于基金会，允许为空。

---

### 步骤 ⑥ — Organization 向下扩展热门项目（脚本 + 人工）

**目的**：对步骤 ③ 已验证的有效组织，向下寻找热门项目。

**输入**：`output/organizations.csv`（已在步骤 ③ 完成验证和去重）

**向下扩展**：
- **脚本**：调用 GitHub API (`GET /orgs/{org}/repos?sort=stars`) 获取热门 repo
- 筛选条件：最近 1 年内有活跃推送 或 500+ stars；排除 archived、fork、低星项目
- **人工**：审核候选 repo 列表，确认哪些纳入最终结果（排除不相关的内部工具、文档仓库、awesome-list 等）

> **为什么需要人工审核**：自动筛选仅基于 stars 和活跃度，无法判断 repo 与目标领域的相关性，可能纳入不相关项目或遗漏重要但星数不高的核心项目。

**对应模块**：`scripts/expand_orgs.py` + `/expand-orgs` skill

**输出**：
- `output/org_expanded_repos.csv` — 人工审核后，从组织向下扩展发现的热门 repo

---

### 步骤 ⑦ — Foundation 去重 + 向下扩展

**目的**：去重后为每个基金会寻找热门项目。

**输入**：`output/foundations.csv`

**实现方式**：
- **去重**：按标准化名称/URL 去重
- **LLM**：搜索基金会旗下的知名开源项目
- **人工**：审核候选项目列表

**输出**：
- `output/foundations_deduped.csv` — 去重后的基金会列表
- `output/foundation_expanded_repos.csv` — 从基金会向下扩展发现的热门 repo

---

### 步骤 ⑧ — 最终整合输出

**目的**：将所有路径产出的实体汇总为一张大表。

**输入**：
- `output/all_repos.csv`（种子 repo）
- `output/org_expanded_repos.csv`（步骤 ⑥ 扩展的 repo）
- `output/foundation_expanded_repos.csv`（步骤 ⑦ 扩展的 repo）
- `output/organizations.csv`（验证后的组织）
- `output/companies.csv`（公司）
- `output/foundations_deduped.csv`（基金会）

**去重规则**：按 URL 标准化后去重，冲突字段以人工确认值为准

**输出**：`output/final.csv`

```csv
name,url,type,category,organization,company,foundation,stars,last_active,description,evidence
transformers,https://github.com/huggingface/transformers,repo,训练加速,huggingface,Hugging Face Inc.,,136000,2026-03,"NLP library","..."
huggingface,https://github.com/huggingface,organization,,,,Hugging Face Inc.,,,,"GitHub org page"
Hugging Face Inc.,,company,,,,,,,,"https://huggingface.co"
```

| 字段 | 说明 |
|------|------|
| `name` | 实体名称 |
| `url` | 标准化 URL |
| `type` | `repo` / `organization` / `company` / `foundation` |
| `category` | 原始分类（如训练加速、推理加速） |
| `organization` | 所属 GitHub 组织 |
| `company` | 所属公司（可为空） |
| `foundation` | 所属基金会（可为空） |
| `stars` | GitHub star 数（仅 repo） |
| `last_active` | 最后活跃时间（仅 repo） |
| `description` | 描述 |
| `evidence` | 佐证信息 |

---

## 五、文件依赖关系汇总

```
data.csv
  → output/classified.csv           (步骤 ①)
  → output/repos.csv                (步骤 ①)
  → output/non_repos.csv            (步骤 ①)
     → output/non_repos_classified.csv  (步骤 ②)
  → output/all_repos.csv            (合并步骤)
     → output/organizations.csv     (步骤 ③)
     → output/companies.csv         (步骤 ④)
     → output/foundations.csv       (步骤 ⑤)
     → output/org_expanded_repos.csv       (步骤 ⑥)
     → output/foundations_deduped.csv      (步骤 ⑦)
     → output/foundation_expanded_repos.csv (步骤 ⑦)
  → output/final.csv                (步骤 ⑧)
```

---

## 六、已实现模块

| 步骤 | 脚本 | Skill | 状态 |
|------|------|-------|------|
| ① 输入分类 | `scripts/classify.py` | `/classify` | ✅ 已实现 |
| ② LLM + 人工分类 | — | `/classify`（LLM fallback） | ✅ 已实现 |
| 合并 Repo 池 | `scripts/merge_repos.py` | `/merge-repos` | ✅ 已实现 |
| ③ 溯源组织 | `scripts/resolve_orgs.py` | `/resolve-orgs` | ✅ 已实现 |
| ④ 溯源公司 | `scripts/trace_companies.py` | `/trace-companies` | ✅ 已实现 |
| ⑤ 溯源基金会 | `scripts/trace_foundations.py` | `/trace-foundations` | ✅ 已实现 |
| ⑥ Org 扩展 | `scripts/expand_orgs.py` | `/expand-orgs` | ✅ 已实现 |
| ⑦ Foundation 扩展 | `scripts/dedup_foundations.py` | `/expand-foundations` | ✅ 已实现 |
| ⑧ 最终整合 | `scripts/merge_final.py` | `/merge-final` | ✅ 已实现 |

---

## 七、技术要求

### 7.1 依赖

- **GitHub API**：需要 `GITHUB_TOKEN` 环境变量（避免 rate limit）
- **LLM API**：通过 Claude Code skill 调用 Claude 进行分类和信息搜索
- **Python 3.10+**

### 7.2 人工介入点

流程中需要人工确认的环节：
- 步骤 ②：非 repo 实体的最终分类
- 步骤 ③：组织有效性验证（排除个人命名空间、废弃组织）
- 步骤 ④⑤：公司/基金会归属确认
- 步骤 ⑥：组织扩展的候选 repo 审核
- 步骤 ⑦：基金会热门项目审核

统一机制：脚本/LLM 生成带佐证的待审核 CSV → 人工标注 → 下一步读取标注结果继续执行。

### 7.3 持续改进原则

在运行 skill 的过程中，如果发现以下情况，应**立即更新**对应的脚本或 skill，而非仅做一次性处理：

- **脚本逻辑缺陷**：如分类规则遗漏、URL 解析不完整、筛选条件不合理 → 修复 `scripts/*.py`
- **skill 知识过时**：如已知实体列表（foundations、companies）不完整、分类提示词不够准确 → 更新 `.claude/skills/` 中的对应文件
- **重复的人工修正**：如果人工多次修正同一类错误（如某类 org 总是被误判），应将修正规则固化到脚本或 skill 中，避免重复劳动
- **新发现的模式**：如发现新的 URL 格式、新的组织类型等 → 补充到脚本的处理逻辑中

> 核心思路：每次运行都是对工具链的一次检验，发现问题就地修复，让后续运行越来越高效。
