# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
uv sync --extra dev    # install package + dev dependencies into .venv
cp .env.example .env   # configure API keys
```

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Docker.

## Commands

```bash
# Docker (agent server)
make up             # build + run agent server (detached)
make down           # stop containers (workspace data preserved)
make shell          # bash into running container
make logs           # tail agent server logs

# TUI (local)
make ui             # launch TUI connecting to agent server

# Data pipeline (local)
make collect        # snapshot market data + sync Kalshi daily history
make backfill-meta  # backfill kalshi_market_meta from Kalshi API (historical + live)
make backup         # backup DuckDB database
make startup        # dump session state JSON (debug)

# Code quality (local)
make lint           # ruff check + format check + mypy
make format         # ruff fix + format

# Testing (local)
make test           # run unit tests (excludes live API tests)
make test-cov       # run unit tests with coverage report
make test-live      # run live Kalshi API integration tests (requires .env credentials)

```

## Architecture

Kalshi market analysis system built on `claude-agent-sdk`. The system runs as a persistent WebSocket server inside Docker, with a thin Textual TUI client connecting locally. The agent discovers mispricings across Kalshi markets using a combination of programmatic analysis and semantic reasoning — reading settlement rules, understanding cross-market relationships, and writing custom analytical scripts. Produces structured trade recommendations — it does not execute trades directly.

### Server/TUI split

**Agent server** (Docker, persistent, `make up`):
- `server.py` — WebSocket server on port 8765
- Owns the `ClaudeSDKClient` lifecycle (create, query, stream, destroy)
- MCP tools (markets: 5 tools, db: 1 tool)
- Hooks (PreToolUse: auto-approve + file protection, PostToolUse: rec audit + KB commit)
- Session log extraction on clear/idle/shutdown (sends wrap-up prompt, captures prose, writes markdown + DB)
- Crash recovery (deferred session log extraction for unlogged sessions)
- Bridges `AskUserQuestion` to TUI via WebSocket

**TUI client** (local, `make ui`):
- `tui/app.py` — Thin WebSocket client to agent server
- Own `AgentDatabase` connection (reads + execution writes)
- Own `KalshiAPIClient` (portfolio display + trade execution)
- `TUIServices` (execution, portfolio reads — same as before)
- All screens and widgets (rendering from WS messages instead of SDK types)

### Three-layer design

**Programmatic layer** (no LLM, runs separately):
- `collector.py` — snapshots Kalshi market data to DuckDB, syncs daily history from S3
- Run via: `make collect`

**Agent layer** (Claude SDK, runs in server):
- Queries canonical DuckDB views (`v_latest_markets`, `v_daily_with_meta`) for bulk market analysis
- Investigates opportunities using MCP tools for live market data (orderbooks, trades, portfolio)
- Records trade recommendations via `recommend_trade` tool for separate review/execution
- Persists findings to `/workspace/analysis/knowledge_base.md` across sessions

**TUI layer** (Textual, runs locally):
- `tui/app.py` — FinanceApp: WebSocket client, local DB + Kalshi for screens
- `tui/services.py` — async wrappers bridging exchange clients to Textual event loop
- `tui/screens/` — dashboard (chat+sidebar), knowledge base, recommendations, portfolio, history, performance
- `tui/widgets/` — 7 widgets: agent_chat, rec_card, rec_list, portfolio_panel, status_bar, ask_modal, confirm_modal

### WebSocket protocol

JSON messages with a `type` field:

**TUI → Server:** `chat`, `clear`, `interrupt`, `ask_response`
**Server → TUI:** `text`, `tool_use`, `tool_result`, `result`, `ask_question`, `recommendation_created`, `session_reset`, `session_log_saved`, `status`

### Source -> Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`.

**Workspace isolation** (dual-mount pattern):
- `workspace/scripts/` → COPY'd into image at `/workspace/scripts/` (read-only, immutable)
- `workspace/data/` → mounted `:ro` at `/workspace/data/` (kernel-enforced read-only for agent) + `:rw` at `/app/state/` (app code writes DB/logs here, outside agent sandbox)
- `workspace/analysis/` → mounted `:rw` at `/workspace/analysis/` (agent's writable scratch space)

The PreToolUse hook denies Write/Edit to protected paths with helpful messages. Bash writes to `:ro` paths fail at the kernel level.

### Module roles

| Module | Role |
|--------|------|
| `server.py` | `AgentServer`: WS server, SDK client lifecycle, session log extraction, crash recovery, rotation lock |
| `server_main.py` | Server entry point: loads config, setup logging, starts `AgentServer` |
| `main.py` | Assembles `ClaudeAgentOptions` via `build_options()`. Used by `server.py` |
| `config.py` | `Credentials(BaseSettings)` from env; `TradingConfig` + `AgentConfig` dataclasses. Path fields have `FA_*` env var overrides. Also templates `prompts/system.md` |
| `constants.py` | Domain string constants (`EXCHANGE_KALSHI`, `STATUS_PENDING`, `SIDE_YES`, etc.) — import from here, don't hardcode |
| `models.py` | SQLAlchemy ORM (9 tables, DuckDB `Sequence` PKs, `UniqueConstraint` for upserts). Alembic autogenerate source |
| `tools.py` | MCP tool factories: `create_market_tools(kalshi)` → 5 tools, `create_db_tools(db, session_id, kalshi)` → 1 tool. 6 total |
| `database.py` | `AgentDatabase`: DuckDB via `duckdb_engine`, auto-migrations, canonical views, upserts via raw SQL `ON CONFLICT`, CRUD for recs/sessions |
| `kalshi_client.py` | Thin wrapper around `kalshi_python_async` SDK. RSA-PSS auth, rate limiting, paginated `get_events`, historical API methods |
| `collector.py` | Standalone data collector: snapshots markets, syncs daily history from S3, resolves settlements, runs retention purges |
| `backfill.py` | Kalshi daily history sync from public S3. Incremental, parallel downloads (8 workers) |
| `meta_backfill.py` | Bulk metadata backfill for `kalshi_market_meta`. Two-phase: historical API pagination + live API batched `get_markets`. CLI via `make backfill-meta` |
| `hooks.py` | PreToolUse (auto-approve + file protection) + PostToolUse (rec audit + KB commit) |
| `fees.py` | Kalshi fee calculations: `kalshi_fee()`, `best_price_and_depth()`, `compute_hypothetical_pnl()` |
| `kb_versioning.py` | Async git helpers for KB versioning: `commit_kb()`, `get_versions()`, `get_version_content()` |
| `ws_monitor.py` | `KalshiFillMonitor` (WebSocket) + `FillMonitor` (polling fallback) for real-time order fill detection |
| `logging_config.py` | `setup_logging()` — centralized logging, per-session file handler, quiets noisy libraries |
| `rate_limiter.py` | Token-bucket rate limiter with separate read/write buckets |
| `api_base.py` | Base class for API clients with shared rate limiting and serialization |
| `prompts/system.md` | System prompt template: analyst role, prediction market mechanics, DuckDB query rules, risk rules |

### Key patterns

- **Factory + closure** for tools: `create_market_tools(kalshi)` returns a list of `@tool`-decorated functions closed over the Kalshi client.
- **MCP tool naming**: `mcp__markets__{tool_name}`, `mcp__db__{tool_name}`. Two MCP servers, 6 tools total.
- **Conventions**: Prices in cents, action+side, exchange column always "kalshi" in active code. Domain strings (`"kalshi"`, `"pending"`, `"yes"`, `"buy"`, `"manual"`, etc.) defined in `constants.py` — import from there, don't hardcode.
- **Config**: `Credentials` loads from env vars/`.env`; `TradingConfig` and `AgentConfig` are source-level defaults. Path fields on TradingConfig have `FA_*` env var overrides for Docker.
- **Hook ordering**: PreToolUse (auto-approve + file protection) → PostToolUse rec audit + KB commit.
- **Startup context injection**: `server.py` calls `db.get_session_state()` and injects result (including knowledge base content) into system prompt. Agent starts with full context — no tool call needed.
- **Knowledge base**: `/workspace/analysis/knowledge_base.md` — single markdown file the agent reads/writes for persistent memory (watchlist, verified findings, rejected ideas, patterns).
- **Session logging**: On session end (clear, idle, shutdown), server sends wrap-up prompt to existing SDK client, captures prose response, writes to `workspace/analysis/sessions/{session_id}.md` and `session_logs` DB table.
- **Analyst-only**: Agent recommends trades via `recommend_trade` DB tool. Exchange client methods remain for TUI executor.
- **Canonical views**: 3 DuckDB views (`v_latest_markets`, `v_daily_with_meta`, `v_active_recommendations`) replace `markets.jsonl` and provide SQL-native discovery. Created on startup after migrations.
- **DuckDB upserts**: Use raw SQL `text()` with `ON CONFLICT` clauses. `UniqueConstraint` on `kalshi_daily` and PKs on `events`/`kalshi_market_meta` serve as conflict targets.
- **Rotation lock**: `asyncio.Lock` in server.py serializes concurrent session rotations to prevent race conditions.

### Logging

Centralized via `logging_config.py`. Call `setup_logging()` once per entry point; all other modules use `logger = logging.getLogger(__name__)` at module level. Agent server logs to stderr + per-session files in `FA_LOG_DIR`.

## Code style

- **Ruff** for linting and formatting (line length 99, Python 3.13 target)
- **mypy** for type checking (lenient: `ignore_missing_imports`, no strict mode)
- `workspace/` is excluded from linting (agent-authored scripts, not package code)
- Pre-commit hooks run ruff lint + format on every commit
- **SQLAlchemy ORM preferred** — most database queries use ORM `select()`, `insert()`, `update()`, `delete()` on model classes. Upserts use raw SQL `text()` with `ON CONFLICT` for DuckDB compatibility. Add new query methods to `database.py` rather than writing inline SQL.

## Testing

- **pytest** + **pytest-asyncio** (asyncio_mode="auto"), **pytest-cov** for coverage
- `make test` runs unit tests (excludes `@pytest.mark.live`); `make test-cov` adds coverage report
- `make test-live` runs live Kalshi API integration tests (`tests/test_kalshi_live.py`) — requires `.env` credentials and network access. Tests all SDK read methods against the real API to catch deserialization bugs.
- Tests live in `tests/` (core modules) and `tests/tui/` (TUI services, widgets, messages)
- Fixtures in `tests/conftest.py` (temp DuckDB, mock Kalshi client, sample data factories) and `tests/tui/conftest.py` (TUIServices wired to mocks)
- TUI widget tests use Textual's `App.run_test()` / `Pilot` for headless rendering

## Documentation

- **README.md** — project overview, architecture, quickstart, tool reference, database schema, config guide. Keep in sync with CLAUDE.md when making architectural changes (screen counts, tool counts, table counts, removed features, etc.).
