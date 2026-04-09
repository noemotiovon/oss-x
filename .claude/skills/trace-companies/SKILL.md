---
name: trace-companies
description: Use LLM Web Search to determine company affiliation for each repo
user-invocable: true
---

# Company Tracing Skill (Step ⑩)

Determine which repos are backed by commercial companies using Web Search.

## Input

- `output/repo_exp.csv` — expanded repo list (from step ⑧)

## Procedure

### Step 1: Read repos

Read `output/repo_exp.csv` and prepare to process each repo.

### Step 2: LLM Web Search for company affiliation

For each repo, **you MUST use Web Search** to determine company affiliation. Do NOT guess.

#### Research methodology

For each repo:

1. **Check the repo's GitHub page** — description, website URL, and org info often reveal the company
2. **Web search** for `"{project_name}" company OR Inc OR Ltd OR "backed by" OR "developed by" OR "maintained by"`
3. **Check the org's website** — commercial domains often point to the parent company

#### Decision criteria

- **Has parent company**: The repo is owned/maintained by a for-profit company
  - Record company name, confidence, and evidence
- **Independent project**: Community-driven, no single corporate owner
  - Set `company_name=unknown`
- **Multiple sponsors**: Several companies contribute but none owns it
  - Set `company_name=unknown`, note the sponsors in evidence

#### Common patterns

- Chinese tech companies: Huawei/华为, Alibaba/阿里, Tencent/腾讯, Baidu/百度, ByteDance/字节
- US tech: Google, Meta, Microsoft, Amazon, Apple
- AI companies: OpenAI, Anthropic, Hugging Face, Stability AI
- University labs: not companies — mark as `unknown`

#### For each repo, record:

- `company_name` — company name, or `unknown` if not affiliated
- `evidence` — actual URLs and facts from web search
- `confidence` — S/A/B/C

#### Batch optimization

- Group repos by org — repos in the same org usually belong to the same company
- Research the org once, apply to all its repos

### Step 3: Present to user

Show results grouped by company:
- Company name
- Repos under this company
- Evidence and confidence for each

The user reviews and may correct assignments.

### Step 4: Save output

After user confirmation, write `output/company.csv` with columns:
- All repo columns from repo_exp.csv
- `company_name` — company name or `unknown`
- `evidence` — search evidence
- `confidence` — S/A/B/C

### Step 5: Output summary

Print:
- Total repos processed
- Repos with company affiliation (count by company)
- Repos with no company (`unknown`)
- Count by confidence level
