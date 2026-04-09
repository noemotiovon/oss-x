---
name: classify-unknown
description: Use LLM Web Search to classify unknown entities as repo or organization
user-invocable: true
---

# Unknown Classification Skill (Step ②)

For entries marked `unknown` in `output/classified.csv`, use Web Search to determine whether each is a **repo** or **organization**.

## Input

- `output/classified.csv` — from step ① `/classify`

## Procedure

### Step 1: Extract unknown entries

Read `output/classified.csv` and filter rows where `type=unknown`.

If no unknown entries exist, inform the user and skip to next step.

### Step 2: LLM Web Search classification

For each unknown entry, **you MUST use Web Search** to find real information. Do NOT classify from memory or guessing.

#### For each unknown entry:

1. **Web search** for the project name and URL to determine what it is
2. **Determine type**:
   - If it's a single software project / codebase → `repo`
   - If it's a group/community maintaining multiple repos → `organization`
3. **Record evidence**: the actual URLs and facts found via search
4. **Assign confidence**:
   - **S** — Certain, clear official source found
   - **A** — High confidence, multiple reliable sources
   - **B** — Medium confidence, partial sources
   - **C** — Low confidence, indirect information only

#### Decision guidelines

**repo signals**:
- Has a single codebase you can clone or download
- Installable as one package (`pip install X`, `apt install X`)
- Project-specific website (e.g., `openfoam.org`) still counts as repo if it's ONE codebase
- SourceForge/Bioconductor/CRAN packages are repos
- Kernel subsystems (KVM, LVS) are repos

**organization signals**:
- Maintains multiple independent repositories
- URL points to org-level page (no specific repo path)
- Name ends with "社区"/"community"
- Entry lists multiple project URLs in上游地址

### Step 3: Generate output

Write results to `output/unknown.csv` with columns:
`页签,序号,项目名称,分类,上游地址,type,evidence,confidence`

Present results to the user in a table for review. The user may correct any entries.

After user confirmation, save the final `output/unknown.csv`.

### Step 4: Output summary

Print:
- Total unknowns processed
- Count by type (repo / organization)
- Count by confidence (S / A / B / C)
- Any entries the user corrected

### Next step

→ `/split-merge`
