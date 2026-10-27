# PRISM — Architecture Plan

## Persistent Repository Intelligence & Security Mapping

### Overview

PRISM creates a persistent, version-aware understanding of a software repository and explains new code changes in clear English for security reviewers. It complements existing tools (Coverity, Black Duck) rather than replacing them.

### Core Principle

**The repository's source code and Git history are the source of truth. AI-generated summaries are secondary, versioned artifacts.**

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Next.js Frontend                          │
│  Pixel-water R3F background · shadcn/ui · React Flow graphs  │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
┌──────────────────────────┴──────────────────────────────────┐
│                   FastAPI Backend                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ API Routes│ │ Webhooks │ │ MCP Tools│ │ Health/Ready │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────────────┘   │
│       │             │             │                           │
│  ┌────┴─────────────┴─────────────┴──────────────────┐      │
│  │              Service Layer                           │      │
│  │  GitMirror · Indexer · Review · Explanation · Policy │      │
│  └────┬─────────────────────────────────────┬────────┘      │
│       │                                     │                │
│  ┌────┴────┐                          ┌─────┴──────┐         │
│  │ SQLite  │                          │  LLM (Ollama)│       │
│  │ (pg)    │                          │  Provider   │        │
│  └─────────┘                          └────────────┘         │
└─────────────────────────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │   Background Worker       │
              │   (asyncio task queue)    │
              └──────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │   Persistent Git Mirror  │
              │   (on-disk bare repos)   │
              └──────────────────────────┘
```

### Layers

1. **Git Mirror** — Persistent on-disk Git mirror per repository. Fetches incrementally, never full-clone per PR.
2. **Code Index** — Tree-sitter based symbol/relationship extraction. Content-hash keyed for incremental reuse.
3. **LLM Provider** — Abstraction over Ollama (default) with constrained JSON output. Configurable model.
4. **Review Engine** — Gathers evidence, builds structured report, applies deterministic policy rules.
5. **MCP Tools** — Read-only, permission-aware tools the LLM uses to query repo intelligence.
6. **Worker** — Async background jobs for ingestion and analysis with status tracking and retries.

### Data Model (SQLite, swappable to PostgreSQL)

- `repositories` — repo URL, provider, mirror path, default branch
- `branches` — tracked branches per repository
- `commits` — SHA, message, author, timestamp, parent SHAs
- `index_versions` — per-repo, per-commit index version with status
- `files` — path, content hash, language, line count
- `symbols` — name, type, file, line range, signature, content hash
- `relationships` — src symbol, dst symbol, type (imports/calls/refs)
- `pull_requests` — PR number, title, author, base/head SHAs
- `analysis_jobs` — type, status, repository, commit, error, progress
- `findings` — analysis run, severity, evidence refs, confidence
- `evidence_refs` — finding, file path, line range, commit, source type
- `review_reports` — structured report JSON, review state
- `scanner_results` — scanner name, commit, raw/processed findings
- `policies` — required checks, risk thresholds
- `audit_events` — action, actor, repository, timestamp, details

### Incremental Indexing

1. On new commit: fetch missing objects into existing mirror.
2. Compare base/head trees to identify changed files.
3. Compute content hash per changed file.
4. If hash unchanged → reuse existing symbol/relationship index entries.
5. If hash changed → re-parse with Tree-sitter, rebuild affected entries.
6. Full re-index only on schema change or integrity reconciliation.

### Review States (deterministic, not LLM-generated)

- `READY_FOR_POLICY_REVIEW` — all checks pass, no blocking findings
- `REVIEW_REQUIRED` — manual review needed (standard default)
- `BLOCKED_BY_FINDING` — high-severity finding with evidence
- `ANALYSIS_INCOMPLETE` — indexing or analysis not finished
- `FAILED_CHECKS` — CI/test/scanner checks failed
- `HUMAN_SECURITY_REVIEW_REQUIRED` — security-sensitive change detected

### Technology Stack

| Component | Technology |
|-----------|-----------|
| Frontend | Next.js (App Router) + TypeScript |
| UI | Tailwind CSS + shadcn/ui + Lucide |
| 3D Background | React Three Fiber (Three.js) |
| Graph Viz | React Flow |
| Backend | Python + FastAPI |
| Validation | Pydantic v2 |
| DB | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLAlchemy 2.0 |
| Git | GitPython |
| Parsing | Tree-sitter (multi-language) |
| LLM | Ollama (Qwen2.5-Coder 7B baseline) |
| Tests | Pytest (backend) + Vitest (frontend) |

### Security Posture

- Repository content treated as untrusted input
- SSRF protection on repo URL validation
- No arbitrary shell execution from LLM output
- Webhook signature verification
- Secret redaction in logs
- Read-only MCP tools by default
- Audit logging for all repo access
