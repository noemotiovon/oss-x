---
name: trace-foundations
description: Trace repos/organizations to their parent foundations, output foundations.csv
user-invocable: true
---

# Foundation Tracing Skill (Step ⑤)

Trace each repo/organization to its parent open-source foundation using known mappings, LLM research, and human confirmation.

## Input

- `output/all_repos.csv` — full repo pool (from merge step)
- `output/organizations.csv` — verified organizations (from step ③)

## Procedure

### Step 1: Run the prep script

```bash
python3 scripts/trace_foundations.py output/all_repos.csv output/organizations.csv \
    --summary -o output/foundations_candidates.csv
```

- If exit code is **0** — all owners have known foundation mappings, go to Step 3.
- If exit code is **1** — some owners need LLM research, proceed to Step 2.

### Step 2: LLM research for unknown foundation affiliations

For each row in `output/foundations_candidates.csv` where `confidence=unknown`, research the foundation affiliation.

#### Research methodology

For each unknown owner/org:

1. **Check CNCF landscape** — search `"{project_name}" site:landscape.cncf.io` or `"{project_name}" CNCF`
2. **Check Apache incubator** — search `"{project_name}" site:apache.org`
3. **Check Linux Foundation projects** — search `"{project_name}" site:linuxfoundation.org`
4. **General search** — `"{project_name}" foundation OR "open source foundation" OR governance`

#### Decision criteria

- **Has parent foundation**: The project is officially under a foundation's governance
  - Set `foundation` to the foundation name, `confidence` to `high`, `source` to `LLM研究: {evidence}`
- **No foundation**: Independent/community project or corporate-controlled
  - Set `foundation` to empty, `confidence` to `none`, `source` to `LLM研究: 独立项目`
- **Ambiguous**: May be in incubation or transitioning
  - Set `foundation` to best guess, `confidence` to `low`, `source` to `LLM研究: {details}`

#### Key foundations to check

- **CNCF** (Cloud Native Computing Foundation) — Kubernetes ecosystem
- **Apache Software Foundation** — Big data, middleware
- **Linux Foundation** — Kernel, networking, AI/ML (LF AI & Data, PyTorch Foundation)
- **Eclipse Foundation** — IDE, IoT, Jakarta EE
- **OpenInfra Foundation** — OpenStack, StarlingX
- **OpenJS Foundation** — Node.js, jQuery, webpack, Electron
- **Python Software Foundation** — CPython, pip, PyPI
- **Rust Foundation** — Rust compiler, Cargo
- **GNOME Foundation**, **KDE e.V.**, **Mozilla Foundation**, etc.

#### Batch optimization

- CNCF has a public landscape — check it first for cloud-native projects
- Apache projects always have `apache.org` domains
- LF sub-foundations (LF AI, LF Edge, LF Networking) are under the Linux Foundation umbrella

After research, update `output/foundations_candidates.csv` with findings.

### Step 3: Generate foundations.csv

From the completed candidates file, produce the final deduplicated foundation list.

**Present candidates to the user for review** before generating the final file. Group by foundation and show:
- Foundation name
- Associated orgs/repos
- Evidence/source

After user confirmation, generate `output/foundations.csv` with columns:

```
foundation,url,associated_orgs,associated_repos,evidence
```

Where:
- `foundation` — Foundation name
- `url` — Foundation website
- `associated_orgs` — Semicolon-joined list of GitHub orgs under this foundation
- `associated_repos` — Semicolon-joined list of key repos
- `evidence` — How the affiliation was determined

Deduplicate by foundation name (case-insensitive).

### Step 4: Self-improvement

If you identified new foundation → org mappings, add them to `KNOWN_FOUNDATIONS` in `scripts/trace_foundations.py` so future runs auto-classify them. Ask the user before making changes.
