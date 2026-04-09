# Open Source 生态发现流水线 — 实现指南

## 一、背景

我们有一批待分析的开源项目/实体（data.csv），目标是：以这批种子数据为起点，**向上溯源**找到所属的组织、公司、基金会，再**向下扩展**发现热门项目，最终输出包含 repo、organization、company、foundation 及佐证信息的完整表格。

整个流程为**单向线性流水线**（无循环），涉及 **脚本自动化**、**GitHub API**、**LLM（Claude Code Web Search）**、**人工确认** 四种角色的配合。

> **重要原则**：LLM 的所有信息必须通过 Web Search 真实获取，不允许主观臆断。所有步骤只读取上游文件、生成新文件，**不修改原始 CSV**。

---

## 二、输入格式

`data.csv`，每行代表一个待分析的实体：

```csv
页签,序号,项目名称,*分类,*上游地址
昇腾,1,transformers,训练加速,https://github.com/huggingface/transformers
```

---

## 三、流程总览

```
data.csv
  │
  ▼
┌───────────────────────────────────────────┐
│ ① 输入分类（GitHub API + 脚本）              │
│   判断 repo / organization / unknown        │
│   → output/classified.csv                   │
└──────┬────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────┐
│ ② Unknown 分类（LLM + 人工）                 │
│   对 unknown 条目通过 LLM 判断类型             │
│   → output/unknown.csv                      │
└──────┬────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────┐
│ ③ 拆分合并（脚本）                            │
│   按类型拆分到 repo.csv / organization.csv    │
│   → output/repo.csv                         │
│   → output/organization.csv                 │
└──────┬────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────┐
│ ④ Repo 溯源组织（GitHub API + 脚本）          │
│   查询每个 repo 的 org，已知的聚合               │
│   → output/repo_known_org.csv               │
│   → output/repo_unknown_org.csv             │
└──────┬────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────┐
│ ⑤ Unknown Org 补全（LLM + 人工）             │
│   对未知 org 的 repo 通过 LLM 搜集组织信息      │
│   → output/repo_unknown_org.csv（更新）      │
└──────┬────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────┐
│ ⑥ 组织合并去重（脚本）                         │
│   三份组织来源合并去重                          │
│   → output/org_exp.csv                      │
└──────┬────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────┐
│ ⑦ 组织有效性验证（脚本 + GitHub API + LLM + 人工）│
│   验证每个组织是否有效                          │
│   → output/org_exp_val.csv                  │
└──────┬────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────┐
│ ⑧ Repo 扩展（GitHub API + LLM + 人工）       │
│   从有效组织扩展热门仓库                        │
│   → output/repo_exp.csv                     │
└──────┬────────────────────────────────────┘
       │
       ├──────────────────────┐
       ▼                      ▼
┌─────────────────┐  ┌─────────────────┐
│ ⑨ 溯源基金会      │  │ ⑩ 溯源公司       │
│  (LLM + 人工)    │  │  (LLM + 人工)    │
│  → foundation.csv│  │  → company.csv   │
└─────────────────┘  └─────────────────┘
```

---

## 四、各步骤详细说明

### 步骤 ① — 输入分类（GitHub API + 脚本）

**目的**：根据上游地址，通过 GitHub API 判断每个条目的类型。

**输入**：`data.csv`

**实现方式**：
1. 解析上游地址，提取 GitHub 路径
2. 若符合 `github.com/{owner}/{repo}` 格式，调用 `GET /repos/{owner}/{repo}`：
   - 返回成功 → 类型为 `repo`
3. 若符合 `github.com/{owner}` 格式（无 repo 名），调用 `GET /orgs/{owner}`：
   - 返回成功 → 类型为 `organization`
4. 以上均不匹配或 API 返回 404 → 标记为 `unknown`

**对应模块**：`scripts/classify.py` + `/classify` skill

**输出**：
- `output/classified.csv` — 全量结果，包含 `type` 列（repo / organization / unknown）

---

### 步骤 ② — Unknown 分类（LLM + 人工）

**目的**：对步骤 ① 中标记为 unknown 的条目，通过 LLM Web Search 判断类型。

**输入**：`output/classified.csv`（筛选 type=unknown 的行）

**LLM 职责**：
- 通过 Web Search 搜索该项目/实体的信息
- 判断类型为 `repo` 还是 `organization`
- 给出判断依据（搜索到的事实信息）
- 给出可信度等级：**S**（确定）、**A**（高可信）、**B**（中等）、**C**（低可信）

**人工职责**：
- 校验 LLM 的判断结果
- 修正类型和可信度

**对应模块**：`/classify-unknown` skill

**输出**：
- `output/unknown.csv` — 包含列：原始字段 + `type`、`evidence`（判断依据）、`confidence`（S/A/B/C）

---

### 步骤 ③ — 拆分合并（脚本）

**目的**：将 classified.csv 和 unknown.csv 中的条目按类型拆分。

**输入**：
- `output/classified.csv`（type=repo 和 type=organization 的行）
- `output/unknown.csv`（人工确认后的结果）

**实现方式**：
- 从两个输入文件中，type=repo 的合并到 `repo.csv`
- type=organization 的合并到 `organization.csv`

**对应模块**：`scripts/split_merge.py` + `/split-merge` skill

**输出**：
- `output/repo.csv` — 全量 repo 列表
- `output/organization.csv` — 全量 organization 列表

---

### 步骤 ④ — Repo 溯源组织（GitHub API + 脚本）

**目的**：查询每个 repo 所属的 GitHub 组织，区分已知和未知。

**输入**：`output/repo.csv`

**实现方式**：
1. 对每个 repo，调用 GitHub API 获取 `owner` 信息
2. 若 `owner.type == Organization`，记录对应的 org
3. **已知 org 的处理**：
   - 将相同组织的 repo 行进行合并
   - 统计每个组织下的 repo 总数
   - 对页签、项目名称、分类、上游地址进行聚合
   - 写入 `repo_known_org.csv`
4. **未知 org 的处理**：
   - GitHub API 无法查到 org 的（如个人账号、非 GitHub 项目）
   - 直接写入 `repo_unknown_org.csv`，不聚合

**对应模块**：`scripts/resolve_orgs.py` + `/resolve-orgs` skill

**输出**：
- `output/repo_known_org.csv` — 已知组织的聚合结果，列：org_name, org_url, repo_count, 页签(聚合), 项目名称(聚合), 分类(聚合), 上游地址(聚合)
- `output/repo_unknown_org.csv` — 未知组织的 repo 列表，保留原始列

---

### 步骤 ⑤ — Unknown Org 补全（LLM + 人工）

**目的**：对步骤 ④ 中未能通过 GitHub API 确定组织的 repo，通过 LLM 搜集组织信息。

**输入**：`output/repo_unknown_org.csv`

**LLM 职责**：
- 针对每一行 repo，通过 Web Search 搜集其所属组织信息
- 给出组织名称和判断依据
- 给出可信度等级：**S**、**A**、**B**、**C**

**人工职责**：
- 校验 LLM 判断的组织归属是否合理
- 修正组织名称

**对应模块**：`/resolve-unknown-orgs` skill

**输出**：
- `output/repo_unknown_org.csv`（更新）— 增加列：`org_name`、`org_url`、`evidence`、`confidence`

---

### 步骤 ⑥ — 组织合并去重（脚本）

**目的**：将三个来源的组织信息合并为一份去重的组织列表。

**输入**：
- `output/organization.csv`（步骤 ③ 产出，原始输入中直接标记为 organization 的）
- `output/repo_known_org.csv`（步骤 ④ 产出，GitHub API 查到的 org）
- `output/repo_unknown_org.csv`（步骤 ⑤ 产出，LLM + 人工确认的 org）

**实现方式**：
- 按组织名称/URL 去重
- 保留 `repo_known_org.csv` 的所有列结构
- 合并各来源的 repo 统计信息

**对应模块**：`scripts/merge_orgs.py` + `/merge-orgs` skill

**输出**：
- `output/org_exp.csv` — 去重后的完整组织列表

---

### 步骤 ⑦ — 组织有效性验证（脚本 + GitHub API + LLM + 人工）

**目的**：验证每个组织是否为有效的、有意义的开源组织。

**输入**：`output/org_exp.csv`

**实现方式**（分三层）：

1. **脚本自动判断**：
   - 若组织在 csv 中已包含的 repo 数量 > 1，默认为有效
   - 备注：`判断方式=脚本(repo数量>1)`

2. **GitHub API 检索**（针对 GitHub 上的组织）：
   - 查询该组织的仓库总数
   - 查询 star > 100 的仓库数量
   - 查询活跃仓库数量（最近 1 年有推送）
   - 由人工根据以上数据判断是否有效

3. **LLM Web Search**（针对非 GitHub 组织）：
   - 通过 LLM 搜索该组织的相关信息
   - 列出其主要仓库/项目
   - 由人工判断是否有效

**对应模块**：`scripts/validate_orgs.py` + `/validate-orgs` skill

**输出**：
- `output/org_exp_val.csv` — 包含新增列：`is_valid`（true/false）、`total_repos`、`star_gt100`、`active_repos`、`validation_method`（脚本/GitHub API/LLM）、`validation_evidence`

---

### 步骤 ⑧ — Repo 扩展（GitHub API + LLM + 人工）

**目的**：基于原始组织列表，扩展发现更多热门且活跃的仓库。

**输入**：
- `output/repo.csv`（原始 repo 列表）
- `output/organization.csv`（原始组织列表，来自步骤 ③）

**实现方式**：
1. 首先将 `repo.csv` 的所有行写入 `repo_exp.csv`
2. 对 `organization.csv` 中的 GitHub 组织：
   - **GitHub API**：查询该组织下 **star > 100 且近 1 年活跃**（pushed in last year）的仓库，添加到 `repo_exp.csv`
   - **LLM Web Search**（非 GitHub 组织）：搜索该组织的热门仓库，添加到 `repo_exp.csv`，备注来源为 LLM
3. 标注每行的来源：`source=repo`（原始输入）或 `source=org_expansion`（组织扩展）
4. 若同一仓库在 repo.csv 和扩展结果中都存在，以 repo（原始输入）优先
5. 由人工审核扩展出的仓库

**对应模块**：`scripts/expand_repos.py` + `/expand-repos` skill

**输出**：
- `output/repo_exp.csv` — 扩展后的完整 repo 列表，包含 `source` 列和 `llm_note` 列

---

### 步骤 ⑨ — 溯源基金会（脚本 + LLM + 人工）

**目的**：判断每个 repo 是否隶属于某个开源基金会。

**输入**：`output/repo_exp.csv`

**实现方式**（3 层策略）：

1. **缓存匹配**（脚本）：
   - 先通过 LLM Web Search 检索各大基金会（Apache、CNCF、LF、Eclipse 等）的项目列表
   - 保存到 `output/.cache/foundation_projects.json`
   - 脚本遍历 repo 时，优先从缓存中匹配

2. **组织名启发式匹配**（脚本）：
   - 内置 GitHub org → 基金会映射（如 `apache/*` → Apache，`kubernetes/*` → CNCF）
   - 自动匹配已知组织

3. **LLM Web Search**（兜底）：
   - 对缓存和启发式均未匹配的 repo，通过 LLM 逐个搜索基金会归属
   - 如发现新的大型基金会，更新缓存和脚本映射表后重新运行
   - 给出可信度等级：**S**、**A**、**B**、**C**

**人工职责**：
- 校验 LLM 判断的基金会归属是否合理

**对应模块**：`scripts/trace_foundations.py` + `/trace-foundations` skill

**输出**：
- `output/foundation.csv` — 列：repo 信息 + `foundation_name`、`evidence`、`confidence`（S/A/B/C）

---

### 步骤 ⑩ — 溯源公司（LLM + 人工）

**目的**：判断每个 repo 是否隶属于某个商业公司。

**输入**：`output/repo_exp.csv`

**LLM 职责**：
- 通过 Web Search 判断每个 repo 是否由某公司主导开发或维护
- 不属于公司的标注 `unknown`
- 给出信息来源（搜索到的 URL 等）
- 给出可信度等级：**S**、**A**、**B**、**C**

**人工职责**：
- 校验公司归属的合理性

**对应模块**：`/trace-companies` skill

**输出**：
- `output/company.csv` — 列：repo 信息 + `company_name`、`evidence`、`confidence`（S/A/B/C）

---

## 五、角色职责说明

| 角色 | 职责 | 原则 |
|------|------|------|
| **脚本** | URL 解析、GitHub API 调用、CSV 合并/去重/拆分 | 确定性逻辑，可重复执行 |
| **GitHub API** | 验证 repo/org 存在性、获取 owner 信息、获取 org 统计数据 | 真实数据源，需要 `GITHUB_TOKEN` |
| **LLM (Web Search)** | 搜集 GitHub API 无法获得的信息，进行分类判断 | **必须通过 Web Search 获取真实信息，不允许主观臆断** |
| **人工** | 最终确认所有 LLM 判断的结果 | 所有 LLM 输出均需人工校验 |

### 可信度等级说明

| 等级 | 含义 |
|------|------|
| **S** | 确定，有明确官方来源佐证 |
| **A** | 高可信，有多个可靠来源佐证 |
| **B** | 中等可信，有部分来源但不够权威 |
| **C** | 低可信，仅基于间接信息推断 |

---

## 六、文件依赖关系汇总

```
data.csv
  → output/classified.csv                (步骤 ①)
     → output/unknown.csv                (步骤 ②)
  → output/repo.csv                      (步骤 ③)
  → output/organization.csv              (步骤 ③)
     → output/repo_known_org.csv         (步骤 ④)
     → output/repo_unknown_org.csv       (步骤 ④→⑤)
  → output/org_exp.csv                   (步骤 ⑥)
     → output/org_exp_val.csv            (步骤 ⑦)
  → output/repo_exp.csv                  (步骤 ⑧)
     → output/foundation.csv             (步骤 ⑨)
     → output/company.csv                (步骤 ⑩)
```

---

## 七、Skill 与脚本对应关系

| 步骤 | Skill | 脚本 | 执行方式 | 状态 |
|------|-------|------|---------|------|
| ① 输入分类 | `/classify` | `scripts/classify.py` | GitHub API + 脚本 | 待实现 |
| ② Unknown 分类 | `/classify-unknown` | — | LLM + 人工 | 待实现 |
| ③ 拆分合并 | `/split-merge` | `scripts/split_merge.py` | 脚本 | 待实现 |
| ④ Repo 溯源组织 | `/resolve-orgs` | `scripts/resolve_orgs.py` | GitHub API + 脚本 | 待实现 |
| ⑤ Unknown Org 补全 | `/resolve-unknown-orgs` | — | LLM + 人工 | 待实现 |
| ⑥ 组织合并去重 | `/merge-orgs` | `scripts/merge_orgs.py` | 脚本 | 待实现 |
| ⑦ 组织有效性验证 | `/validate-orgs` | `scripts/validate_orgs.py` | 脚本 + GitHub API + LLM + 人工 | 待实现 |
| ⑧ Repo 扩展 | `/expand-repos` | `scripts/expand_repos.py` | GitHub API + LLM + 人工 | 待实现 |
| ⑨ 溯源基金会 | `/trace-foundations` | `scripts/trace_foundations.py` | 脚本 + LLM + 人工 | 待实现 |
| ⑩ 溯源公司 | `/trace-companies` | — | LLM + 人工 | 待实现 |

---

## 八、技术要求

### 8.1 依赖

- **GitHub API**：需要 `GITHUB_TOKEN` 环境变量（避免 rate limit）
- **LLM**：通过 Claude Code 的 Web Search 能力搜集真实信息
- **Python 3.10+**

### 8.2 人工介入点

| 步骤 | 人工介入内容 |
|------|-------------|
| ② | 校验 unknown 条目的类型判断 |
| ⑤ | 校验 LLM 搜集的组织归属 |
| ⑦ | 根据 GitHub API / LLM 提供的数据判断组织是否有效 |
| ⑧ | 审核从组织扩展出的仓库 |
| ⑨ | 校验基金会归属 |
| ⑩ | 校验公司归属 |

统一机制：脚本/LLM 生成带佐证和可信度的待审核 CSV → 人工标注 → 下一步读取标注结果继续执行。

### 8.3 设计原则

- **职责单一**：每个步骤只做一件事，输入输出明确
- **真实数据**：LLM 必须通过 Web Search 获取真实信息，所有判断必须有来源佐证
- **可信度标注**：LLM 判断必须附带 S/A/B/C 可信度等级
- **人工兜底**：所有 LLM 的输出均需人工校验
- **不修改原始数据**：每步只读取上游文件、生成新文件
- **持续改进**：运行中发现的模式和规则应固化到脚本中
