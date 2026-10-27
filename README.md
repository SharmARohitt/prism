# PRISM

## Persistent Repository Intelligence & Security Mapping

**Understand the change. Explain the risk. Prove the review.**

PRISM creates a persistent, version-aware understanding of a software repository and explains new code changes in clear English for security reviewers — including reviewers who are not deeply technical. Every claim links to real source evidence.

---

## Table of Contents

1. [What PRISM does](#what-prism-does)
2. [Technology stack](#technology-stack)
3. [How PRISM mirrors a repository](#how-prism-mirrors-a-repository)
4. [How auto-sync keeps it up to date](#how-auto-sync-keeps-it-up-to-date)
5. [How everything connects](#how-everything-connects)
6. [Architecture overview](#architecture-overview)
7. [Quick start](#quick-start)
8. [Environment variables](#environment-variables)
9. [API endpoints](#api-endpoints)
10. [What is implemented vs. not yet supported](#what-is-implemented-vs-not-yet-supported)
11. [Limitations and honesty](#limitations-and-honesty)

---

## What PRISM does

When you connect a repository, PRISM:

1. Creates a **persistent on-disk Git mirror** — one clone, reused forever.
2. **Indexes every source file** with Tree-sitter, extracting functions, classes, methods, imports, and call relationships.
3. Stores everything in a **structured database** with commit SHA and index version tracking.
4. **Auto-syncs every 5 minutes** (configurable) by running a lightweight `git fetch` and checking whether the remote HEAD changed.
5. When new commits arrive, runs an **incremental re-index** — only changed files are re-parsed; unchanged files reuse existing index entries by content hash.
6. For each commit, **generates a plain-English explanation** via a local LLM (Qwen2.5-Coder 7B via Ollama) of what changed and why it matters.
7. Builds an **interactive architecture graph** at module, file, and symbol levels — with dead code detection, security-sensitive flags, and evidence-backed relationship labels.
8. For pull requests, runs a **full security review** using deterministic policy rules (not AI guesses) to compute one of six review states.

---

## Technology stack

### Frontend

| Technology | Version | Purpose |
|------------|---------|---------|
| **Next.js** | 14.2 | React framework with App Router, server-rendered pages |
| **TypeScript** | 5.4 | Type-safe frontend code |
| **Tailwind CSS** | 3.4 | Utility-first styling |
| **shadcn/ui primitives** | custom | Accessible UI components (Button, Badge, Card, Tabs…) |
| **React Flow** | 11.11 | Interactive node-graph canvas for the architecture graph |
| **Dagre** | — | Hierarchical graph layout algorithm (TB/LR direction) |
| **React Three Fiber** | 8.17 | Three.js wrapper for the pixel-water animated background |
| **Three.js** | 0.166 | WebGL rendering of the signature water-grid background |
| **Lucide React** | 0.395 | Icon library |
| **SWR** | 2.2 | Data fetching and cache |

### Backend

| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.11+ | Core runtime |
| **FastAPI** | 0.115 | Async REST API framework |
| **Pydantic v2** | 2.14 | Request/response validation and schema enforcement |
| **Pydantic Settings** | 2.16 | Environment-variable configuration |
| **SQLAlchemy** | 2.1 | Async ORM with SQLite (dev) / PostgreSQL (prod) |
| **aiosqlite** | 0.22 | Async SQLite driver |
| **GitPython** | 3.2 | Git repository operations (clone, fetch, diff, log) |
| **Tree-sitter** | 0.26 | Incremental parser for multi-language symbol extraction |
| tree-sitter-python/js/ts/java/go/rust/… | — | Grammar packages for each supported language |
| **httpx** | 0.28 | Async HTTP client for Ollama API + GitHub API |
| **structlog** | 24.4 | Structured JSON logging with secret redaction |

### LLM

| Technology | Purpose |
|------------|---------|
| **Ollama** | Local LLM runtime — no code sent to external services |
| **Qwen2.5-Coder 7B** | Default model — best quality that fits 16 GB RAM (~4.7 GB, 4-bit quantized) |
| Provider abstraction | Swap models via `OLLAMA_MODEL` env var. Falls back to deterministic analysis if Ollama is unavailable. |

### Storage

| Store | Technology | What it holds |
|-------|-----------|--------------|
| Application database | SQLite / PostgreSQL | Repositories, commits, index versions, symbols, relationships, findings, review reports, audit events |
| Git mirrors | On-disk bare Git clones | Full repository objects — never stored in the database |
| Symbol index | Database tables | FileEntry, Symbol, Relationship records keyed by index version |
| Commit explanations | Cached on Commit record | LLM-generated explanations cached after first generation |

---

## How PRISM mirrors a repository

When you connect a repository URL, this happens step by step:

```
User → POST /api/repositories { url: "https://github.com/owner/repo" }
         │
         ├─ URL validated (SSRF protection: blocks 169.254.x, 10.x, private IPs)
         ├─ Repository record created in DB
         ├─ Initial ingestion job enqueued
         └─ Returns repository record immediately
                 │
                 ▼
         Background Worker picks up job
                 │
         ┌──────┴────────────────────────────────┐
         │       handle_initial_ingestion()       │
         │                                        │
         │ 1. GitMirror.fetch()                   │
         │    → git clone https://... (first run) │
         │    → git fetch (if mirror exists)      │
         │                                        │
         │ 2. mirror.analyze_structure()          │
         │    → Walk repo tree: languages,         │
         │      build files, CI files, test files  │
         │                                        │
         │ 3. CodeIndexer.index_repository()      │
         │    → Per file: Tree-sitter parse       │
         │    → Extract symbols + relationships   │
         │    → Content-hash check (reuse if      │
         │      unchanged since last run)         │
         │                                        │
         │ 4. Persist to DB:                      │
         │    FileEntry, Symbol, Relationship,    │
         │    IndexVersion, Commit records        │
         │                                        │
         │ 5. Branch.last_synced_at = now         │
         │    Branch.head_commit_sha = HEAD SHA   │
         └────────────────────────────────────────┘
```

The on-disk mirror lives at `GIT_MIRROR_DIR/{repo_id}/`. It is a real Git repository. Every subsequent operation reuses it — there is no re-clone per PR or per commit.

---

## How auto-sync keeps it up to date

**The problem:** Without webhooks, PRISM would never know about new commits. GitHub webhooks require a public URL and setup on the repository. PRISM solves this with a **background polling loop** that runs inside the FastAPI process.

```
App startup
   │
   └─ AutoSyncScheduler.start()
         │
         ├─ waits 30 seconds (grace period for app init)
         │
         └─ every SYNC_INTERVAL_SECONDS (default: 300s = 5 min)
               │
               ├─ Load up to SYNC_BATCH_SIZE active repositories
               │   (sorted by oldest-synced-first)
               │
               ├─ For each repo (with 2-second stagger):
               │   │
               │   ├─ GitMirror.fetch()
               │   │   → git fetch +refs/heads/*:refs/remotes/origin/*
               │   │   → Downloads any new objects from GitHub/GitLab
               │   │
               │   ├─ mirror.get_head_sha()
               │   │   → What is the remote's current HEAD?
               │   │
               │   ├─ Compare with DB: Branch.head_commit_sha
               │   │   and latest IndexVersion.commit_sha
               │   │
               │   ├─ If SHA unchanged → update last_synced_at, skip
               │   │
               │   └─ If SHA changed → new commits detected!
               │       │
               │       ├─ Update Branch.head_commit_sha
               │       ├─ Check: is a job already running for this repo?
               │       │   (idempotency guard — never double-enqueues)
               │       │
               │       └─ Enqueue incremental_index job
               │             │
               │             ▼
               │   handle_incremental_index()
               │       → fetch again (ensure objects present)
               │       → diff prev_indexed_sha → new_sha
               │       → re-parse only changed files
               │       → reuse unchanged file index entries
               │       → persist new IndexVersion
               │       → store new Commit records with stats
```

**Also available:** `POST /api/repositories/{id}/sync` — triggers an immediate check without waiting for the next poll cycle. The "Sync" button on the dashboard calls this.

**Three sources of updates (layered):**

| Source | Setup required | Latency |
|--------|----------------|---------|
| Background poller | None | ≤ SYNC_INTERVAL (5 min default) |
| Sync button | None | On demand |
| GitHub webhook | GitHub App or webhook config | Near real-time |

All three are idempotent — calling any of them twice for the same SHA produces no duplicate work.

---

## How everything connects

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Next.js Frontend (port 3000)                    │
│                                                                      │
│  Landing page → connects repo → onboarding → dashboard             │
│  Dashboard → Architecture Graph (React Flow + Dagre)                │
│  Timeline → commits + PRs + LLM explanations + approve button       │
│  PR Review → executive summary + technical evidence view            │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ REST API (CORS-allowed)
┌───────────────────────────┴─────────────────────────────────────────┐
│                    FastAPI Backend (port 8000)                       │
│                                                                      │
│  /api/repositories  — connect, list, overview, graph                │
│  /api/repositories/{id}/sync — manual sync trigger                  │
│  /api/repositories/{id}/commits — list + merge detection            │
│  /api/repositories/{id}/commits/{sha}/explain — LLM explanation     │
│  /api/repositories/{id}/architecture-graph — module/file/symbol     │
│  /api/repositories/{id}/pull-requests — list + GitHub sync          │
│  /api/repositories/{id}/pull-requests/{id}/approve — GitHub API     │
│  /api/repositories/{id}/pull-requests/{id}/merge — GitHub API       │
│  /api/repositories/{id}/reviews — start/get PR analysis             │
│  /api/webhooks/github — receive push/PR events                      │
│  /api/mcp/tools — 11 read-only code intelligence tools              │
│  /health, /ready — health checks                                    │
│                                                                      │
│  ┌─────────────────┐  ┌───────────────────┐  ┌──────────────────┐  │
│  │  JobQueue        │  │ AutoSyncScheduler │  │  LLM Provider    │  │
│  │  (asyncio)       │  │ polls every 5 min │  │  Ollama adapter  │  │
│  │  2 workers       │  │ staggered fetch   │  │  constrained JSON│  │
│  └────────┬─────────┘  └────────┬──────────┘  └──────────────────┘  │
│           │                     │                                     │
│  ┌────────┴─────────────────────┴──────────────────────────────────┐ │
│  │                  Core Services                                   │ │
│  │  GitMirror — persistent git fetch, diff, file content           │ │
│  │  CodeIndexer — Tree-sitter multi-language symbol extraction     │ │
│  │  ReviewEngine — evidence gathering + LLM explanation            │ │
│  │  PolicyEngine — deterministic review state (6 states, no AI)    │ │
│  │  GitHub API Client — PR metadata, approve, merge (PAT auth)     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────────────────┼──────────────────────────┐
          │                         │                           │
   ┌──────┴───────┐      ┌──────────┴─────────┐     ┌─────────┴──────┐
   │ SQLite / PG  │      │  On-disk Git mirror │     │  Ollama        │
   │  (database)  │      │  data/git-mirrors/  │     │  port 11434    │
   │              │      │  {repo_id}/         │     │  qwen2.5-coder │
   └──────────────┘      └─────────────────────┘     └────────────────┘
```

---

## Architecture overview

PRISM uses a **layered architecture**:

```
1. Transport layer
   FastAPI routes → parse HTTP, validate with Pydantic, return JSON

2. Orchestration layer
   JobQueue (asyncio) + AutoSyncScheduler → coordinate background work

3. Intelligence layer
   GitMirror → git operations       CodeIndexer → symbol extraction
   ReviewEngine → evidence assembly  PolicyEngine → deterministic rules
   GitHub API Client → outbound PR operations

4. Storage layer
   SQLAlchemy ORM → 14 tables       GitPython → on-disk mirrors

5. LLM layer
   OllamaProvider → targeted explanations only (not safety verdicts)
   StubProvider → deterministic fallback when Ollama unavailable
```

**Key design decisions:**

- **Persistent mirror, not clone-per-PR.** The Git mirror is created once and updated with `git fetch`. No re-clone, no full download per commit.
- **Content-hash keyed incremental indexing.** Unchanged files are never re-parsed. The system detects changes by SHA diff, not by time.
- **Deterministic review states, not AI verdicts.** Six review states (READY, REVIEW_REQUIRED, BLOCKED, INCOMPLETE, FAILED, HUMAN_REQUIRED) are computed by explicit policy rules. The LLM writes explanations; it never decides safety.
- **Evidence-first.** Every claim in a review report links to a file path, line number, and commit SHA.
- **No arbitrary code execution.** Repository content is untrusted input. The LLM cannot execute shell commands or access unrelated files.

---

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Git
- [Ollama](https://ollama.ai) (optional but recommended)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # macOS/Linux

pip install -e ".[dev]"

# Copy and configure environment
cp ../.env.example ../.env
# Edit .env with your settings

uvicorn prism.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

### Ollama (optional)

```bash
# Install from https://ollama.ai
ollama pull qwen2.5-coder:7b
```

Without Ollama, PRISM shows deterministic analysis with a clear "LLM unavailable" note instead of generated explanations.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./prism.db` | SQLite (dev) or `postgresql://...` (prod) |
| `GIT_MIRROR_DIR` | `./data/git-mirrors` | Where persistent Git mirrors are stored |
| `LLM_PROVIDER` | `ollama` | LLM provider (currently only `ollama`) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | Model name — configurable, never hardcoded |
| `BACKEND_HOST` | `127.0.0.1` | Backend bind address |
| `BACKEND_PORT` | `8000` | Backend port |
| `FRONTEND_URL` | `http://localhost:3000` | Allowed CORS origin |
| `WEBHOOK_SECRET` | `change-me` | HMAC secret for webhook verification |
| `GITHUB_TOKEN` | *(empty)* | PAT with `pull_requests:write` + `contents:write` for approval/merge |
| `GITHUB_WEBHOOK_SECRET` | *(empty)* | GitHub-specific webhook HMAC secret |
| `SYNC_INTERVAL_SECONDS` | `300` | How often auto-sync polls each repo. Set to `0` to disable. |
| `SYNC_BATCH_SIZE` | `10` | Max repos checked per sync pass |
| `WORKER_CONCURRENCY` | `2` | Background worker parallelism |
| `JOB_TIMEOUT_SECONDS` | `600` | Max time per indexing job |
| `COVERITY_API_URL` | *(empty)* | Coverity REST API endpoint (adapter interface) |
| `COVERITY_API_TOKEN` | *(empty)* | Coverity auth token |
| `BLACKDUCK_URL` | *(empty)* | Black Duck server URL (adapter interface) |
| `BLACKDUCK_API_TOKEN` | *(empty)* | Black Duck API token |
| `LOG_LEVEL` | `INFO` | Logging level |

To enable GitHub PR approval:
1. Create a PAT at https://github.com/settings/tokens
2. Required scopes: `repo` (or `pull_requests:write` + `contents:write`)
3. Add `GITHUB_TOKEN=ghp_...` to your `.env`

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check with LLM status |
| `GET` | `/ready` | Readiness check |
| `POST` | `/api/repositories` | Connect a repository |
| `GET` | `/api/repositories` | List all connected repositories |
| `GET` | `/api/repositories/{id}` | Get repository details |
| `POST` | `/api/repositories/{id}/sync` | **Immediately check for new commits** |
| `GET` | `/api/repositories/{id}/overview` | Repository overview (languages, stats, commits) |
| `GET` | `/api/repositories/{id}/ingestion-status` | Current indexing job status |
| `GET` | `/api/repositories/{id}/commits` | List commits with merge flags and PR linkage |
| `GET` | `/api/repositories/{id}/commits/{sha}/explain` | LLM explanation of a commit |
| `GET` | `/api/repositories/{id}/graph` | Legacy code graph |
| `GET` | `/api/repositories/{id}/architecture-graph` | Multi-level architecture graph (module/file/symbol) |
| `GET` | `/api/repositories/{id}/architecture-graph/node/{id}` | Node details with evidence |
| `GET` | `/api/repositories/{id}/architecture-graph/search` | Search graph nodes |
| `GET` | `/api/repositories/{id}/architecture-graph/path` | Trace path between two nodes |
| `POST` | `/api/repositories/{id}/reviews` | Start a PR review analysis |
| `GET` | `/api/repositories/{id}/reviews/{prId}` | Get review report |
| `GET` | `/api/repositories/{id}/pull-requests` | List PRs (syncs from GitHub if token set) |
| `POST` | `/api/repositories/{id}/pull-requests/{id}/approve` | Approve PR on GitHub |
| `POST` | `/api/repositories/{id}/pull-requests/{id}/merge` | Merge PR on GitHub |
| `POST` | `/api/webhooks/github` | Receive GitHub push/PR webhooks |
| `GET` | `/api/mcp/tools` | List MCP tool contracts |
| `POST` | `/api/mcp/tools/execute` | Execute a read-only MCP tool |
| `GET` | `/api/settings` | Current settings and integration status |

---

## What is implemented vs. not yet supported

### Implemented

- Repository connection with SSRF-protected URL validation
- Persistent Git mirror with incremental `git fetch`
- **Auto-sync background poller** (every 5 min, configurable)
- **Manual sync endpoint** (`POST /sync` + Sync button in dashboard)
- Tree-sitter code indexing (Python, JS/TS, Java, Go, Rust, Ruby, C/C++, Bash)
- Content-hash keyed incremental re-indexing (only changed files re-parsed)
- Symbol extraction: functions, classes, methods, interfaces, endpoints
- Import and call relationship extraction with evidence classification
- Commit history with real stats (additions/deletions), parent SHAs, merge detection
- PR ↔ commit linkage via merge commit message parsing
- LLM commit explanations (Qwen2.5-Coder via Ollama) — cached per commit
- Multi-level architecture graph (module / file / symbol) with dagre layout
- Dead code detection (orphaned nodes with no incoming or outgoing edges)
- Security-sensitive node flagging (name-based heuristic)
- Node selection with neighborhood highlighting and dimming
- Node details panel (Explain / Technical / Evidence tabs)
- Graph search with debounced lookup
- Scrollable legend with all node types, edge types, evidence classes
- PR review with executive summary + technical evidence view
- Deterministic policy engine (6 review states — never AI-decided)
- GitHub PR approval via PAT (`POST .../approve`)
- GitHub PR merge via PAT (`POST .../merge`)
- Coverity and Black Duck adapter interfaces (documented contracts)
- Webhook signature verification (HMAC-SHA256)
- Secret redaction in structured logs
- Audit events for all approval/merge actions
- 90 automated backend tests passing

### Not yet supported

- Multi-user authorization and repository isolation
- GitLab / Bitbucket webhook support
- pgvector semantic search (PostgreSQL deployment)
- Full taint/data-flow analysis
- Test execution in isolated sandboxes
- Runtime telemetry integration ("last used" data)
- Evaluation harness for benchmarking against known-good reviews
- Retention and data purge policies
- Commit explanation pre-generation (currently on-demand)

---

## Limitations and honesty

- **"No references detected" ≠ dead code.** Dynamic dispatch, reflection, framework registration, and external callers can hide usage. Dead code indicators are labeled "possibly dead" — never "definitely dead."
- **LLM explanations are supplementary.** They describe what changed in plain English but never determine whether a change is safe. Review states are always computed by deterministic policy rules.
- **Scanner integration requires credentials.** Coverity and Black Duck adapters define the contract but need actual API credentials to fetch findings.
- **Static analysis limitations.** Call graphs are limited to statically detectable calls. Runtime behavior cannot be confirmed without execution or telemetry.
- **Auto-sync is polling, not real-time.** The default 5-minute interval means there's up to a 5-minute lag between a push and PRISM indexing it. Use GitHub webhooks for near-real-time updates.
- **Private source code stays local.** No repository content is sent to external services. The LLM runs on-premise via Ollama.

---

## Security posture

- Repository URLs validated against SSRF block-list (metadata endpoints, private IP ranges)
- Webhook signatures verified with HMAC-SHA256
- No arbitrary shell execution from LLM output
- All MCP tools are read-only and enforce repository/commit scope
- Secrets redacted from all log output
- `GITHUB_TOKEN` stored in environment, never in prompts or responses
- Audit events logged for all PR approval and merge actions

---

*PRISM is open-source. Built to complement your existing security tools, not replace them.*
