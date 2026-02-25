# Finance Agent

Kalshi prediction market analysis system built on the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-agent-sdk). Discovers mispricings by combining programmatic SQL analysis with semantic reasoning — reading settlement rules, understanding cross-market relationships, and writing custom analytical scripts. Produces structured trade recommendations for review and execution via a terminal UI.

## Architecture

```
┌──────────────────────┐
│     Textual TUI      │  local process
│  portfolio, rec      │  own DB + Kalshi client
│  review, execution   │  6 screens, 7 widgets
└─────────┬────────────┘
          │ WebSocket (JSON protocol)
┌─────────┴────────────┐
│    Agent Server      │  Docker container
│  Claude SDK client   │  persistent across TUI disconnects
│  6 MCP tools         │  session rotation, crash recovery
│  hooks + sandbox     │  session logging
└─────────┬────────────┘
          │
┌─────────┴────────────┐
│   Data Pipeline      │  standalone, no LLM
│  collector.py        │  DuckDB + S3 daily history
│  ~100M rows OHLC     │  canonical SQL views
└──────────────────────┘
```

The three layers are fully independent. The data pipeline runs on a cron with no LLM cost. The agent server persists inside Docker — closing the TUI doesn't kill the agent. The TUI owns trade execution so the agent can never place orders directly.

## SDK Integration

### Persistent Server with Session Lifecycle

The SDK client runs inside Docker as a long-lived WebSocket server (`server.py`). Sessions rotate on manual clear, serialized via `asyncio.Lock`. On rotation, the server sends a wrap-up prompt to the *existing* `ClaudeSDKClient`, captures the prose summary, writes it to disk and database, then destroys the client and creates a fresh one with new MCP servers and hooks.

### Crash Recovery

The server captures `sdk_session_id` from `ResultMessage` on first response and stores it in the database. On startup, it queries for sessions with no log entry, creates a minimal `ClaudeSDKClient(options=ClaudeAgentOptions(resume=sdk_session_id))` to resume each orphaned session, and runs the wrap-up prompt retroactively. Timeout-bounded with stub fallback — never blocks startup.

### Streaming Response Bridge

`server.py` manually iterates the `client.receive_response()` async generator, dispatching each SDK message type (`AssistantMessage`, `UserMessage`, `ResultMessage`) to the TUI over WebSocket in real-time. Each message type maps to a JSON wire type (`text`, `tool_use`, `tool_result`, `result`). Handles `asyncio.CancelledError` from interrupts and propagates cost/error state.

### Permission Handler as Cross-Process Bridge

The `can_use_tool` callback intercepts `AskUserQuestion`, creates an `asyncio.Future`, sends the question to the TUI via WebSocket, and awaits the response with a 5-minute timeout. Returns `PermissionResultAllow` with updated input containing the user's answers — bridging the SDK's permission model to an async cross-process interaction.

### MCP Tools

Factory+closure pattern: `create_market_tools(kalshi)` returns `@tool`-decorated async functions closed over the exchange client. Two MCP servers created fresh per session via `create_sdk_mcp_server()`: `markets` (5 read-only tools) and `db` (1 write tool).

The `recommend_trade` tool validates agent-specified trades: batch `search_markets` for titles, concurrent `asyncio.gather` for orderbook fetches, maker/taker assignment by depth, position limit checks with fee computation, and DB persistence. The agent specifies action, side, and quantity for each leg.

### Hooks

`PreToolUse`: auto-approves all tools, denies `Write`/`Edit` to read-only Docker mount paths with helpful redirect messages (before kernel-level `:ro` enforcement catches them).

`PostToolUse`: matcher-targeted `audit_recommendation` counts successful recommendations via closure-captured mutable state and fires a server callback; `commit_kb_if_written` auto-commits knowledge base changes to git after any tool modifies it.

### System Prompt Engineering

230-line structured prompt covering binary contract mechanics, data source hierarchy, DuckDB SQL patterns (`CORR()`, `QUALIFY`, window functions), analytical rigor standards, and recommendation protocol. Template variables from `TradingConfig` inject risk limits.

Dynamic session context is built fresh each session and appended to the prompt: last session summary, portfolio snapshot, unreconciled trades, and full knowledge base content. The agent starts with complete context — no tool call needed.

## Sandbox and Isolation

Dual-mount Docker pattern enforces boundaries at the kernel level. `workspace/data/` is mounted `:ro` for the agent but separately mounted `:rw` at `/app/state/` for app code to write the database. `workspace/scripts/` is COPY'd into the image as immutable reference implementations. `workspace/analysis/` is the agent's only writable space.

The `PreToolUse` hook provides helpful denial messages before kernel enforcement catches writes. SDK sandbox config (`autoAllowBashIfSandboxed: true`) allows bash because the filesystem already enforces the boundaries.

## Data Pipeline

Standalone collector (no LLM cost) snapshots open markets and syncs daily OHLC from Kalshi's public S3 bucket — ~100M rows from 2021 to present. DuckDB's columnar engine enables bulk analytical SQL across all markets. Three canonical views (`v_latest_markets`, `v_daily_with_meta`, `v_active_recommendations`) provide SQL-native discovery. A separate metadata backfill bridges S3 data (no titles) to human-readable market names via the Kalshi API.

## Getting Started

**Prerequisites:** Python 3.13+, [uv](https://docs.astral.sh/uv/), Docker, Kalshi API credentials, Anthropic API key

```bash
git clone <repo-url> && cd finance-agent
uv sync --extra dev
cp .env.example .env   # configure API keys

make collect           # collect market data
make up                # start agent server (Docker, detached)
make ui                # launch TUI (connects to server)
```

The server runs persistently — close and reopen the TUI without losing agent state. `make down` stops the server.

## Development

```bash
make test              # unit tests (pytest + pytest-asyncio)
make test-live         # live Kalshi API integration tests
make lint              # ruff + mypy
make format            # auto-fix
```

Ruff for linting/formatting, mypy for type checking, pre-commit hooks enforce both.
