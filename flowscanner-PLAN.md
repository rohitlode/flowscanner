# FlowScanner — Execution Plan (Agent Handoff)

**Audience:** a Claude Code agent picking this up fresh, running on Rohit's personal machine where the repo lives at `/Users/rohitlode/flowscanner/`.
**Repo:** `github.com/rohitlode/flowscanner` (private). Dashboard at `http://localhost:8765`, reachable over Tailscale.
**Status of this plan:** nothing below is implemented yet. Phase 0 is the first thing to build.

---

## 0. Read this first — the governing rule

This is a **money system** (real options trades). The owner's law, quote it back to yourself before every change:

> "If this system is 65, adding something should make it 66, not 64."

Meaning: every change must move a **measured** number up. No speculative complexity, no features that add latency / credit cost / risk without a proven gain. A change you can't measure is not allowed to ship.

**The Needle Test — apply to every PR you open:**
- **Hypothesis:** "This improves [metric] from X to Y."
- **Measurement:** the exact DB column / counter that proves it.
- **Cost:** credits per call, added latency, new failure surface.
- **Kill condition:** if after N signals the metric didn't move, revert it.

You cannot run the Needle Test today because **there is no metric** — the system never records trade outcomes. Building that scoreboard is Phase 0 and is the precondition for everything else.

---

## 1. What the system is

A lightweight options-flow *scanner* inspired by an institutional dashboard. Architecture (deliberately lightweight — do not "upgrade" it to microservices):

```
Claude Code (the scanner)            FastAPI dashboard (the reader)
  ├── calls TradingView MCP tools      ├── reads SQLite
  ├── classifies signals               ├── serves HTMX dark-theme UI
  └── python3 ingest.py '<json>'       └── buttons POST to routes
                    ↓                              ↑
               SQLite (data/signals.db)  ←─────────┘
```

- **Backend:** FastAPI + Uvicorn, Python 3.9 (note: 3.9 — use `from __future__ import annotations` for `X | None` syntax).
- **Frontend:** HTMX + Jinja2 templates, dark theme, no React. Auto-refresh every 30s.
- **Data:** SQLite only.
- **Market data:** TradingView screener (direct HTTP in `scanner.py`) + yfinance + the TradingView MCP (27 tools) available to Claude Code at runtime.
- **Hosting:** launchd auto-restart + Tailscale.

### Files (current state)
| File | What it does |
|---|---|
| `dashboard.py` | FastAPI routes, HTMX responses, auto-scan background thread |
| `db.py` | SQLite schema + signal upsert/query + backtest store |
| `scanner.py` | Direct TradingView screener scan + per-ticker yfinance analysis + signal classification |
| `conviction.py` | Assigns 🔥 HIGH / ⚡ MODERATE / 📊 NO FLOW tiers + sizing |
| `backtester.py` | MACD / RSI / VolBreakout backtests on 1y daily OHLCV |
| `ingest.py` | CLI: `python3 ingest.py '<json>'` → writes signals to DB (called by Claude after MCP scans) |
| `state.py` | File-based flags (auto on/off, scan_requested, interval) |
| `prompts/scan.md`, `prompts/analyze.md` | Prompts Claude runs in headless `claude -p` mode |
| `templates/` | base, flow_trades, scanner, open_trades, analytics, pipeline, report + partials/signal_rows |

### How a scan runs today
Owner tells Claude "run a scan", OR the dashboard's `/scan` route spawns `claude -p prompts/scan.md --mcp-config <path> --allowedTools mcp__tradingview__...`. Claude calls the MCP scanners, classifies, and runs `ingest.py`. There's also an auto-scan thread in `dashboard.py`.

---

## 2. The honest assessment — what's actually broken

The engineering scaffold is a real **65**. But three things **fabricate confidence**, and in a money system fabricated confidence is a hidden liability, not a feature. Plus one cost bug. Fix these before adding anything on top — building features on fiction is a 65→64 (you pay credits/latency to be confidently wrong faster).

**Problem 1 — `VALIDATED_TEST` doesn't validate the trade.**
`backtester.py` backtests a generic MACD/RSI/VolBreakout strategy on the *underlying stock's* 1y daily candles. It is unrelated to the option contract, the DTE, the direction, or the `flow_strategy`. So a bearish `PUT_RISK_OFF` signal can be stamped `VALIDATED_TEST` because a *long* MACD strategy happened to win last year. The badge looks institutional; the math underneath is disconnected. (See `backtester.py` `run_backtest` → `test_bucket`, surfaced as truth in `conviction.py`.)

**Problem 2 — options data is invented.**
`oi_behavior` is computed from price-vs-EMA200 in `scanner.py._classify` (`if price > ema200*1.02 → STUCK_UP …`). Open interest has zero relationship to price-vs-EMA. DTE/OTM are null or hardcoded. The "CONTRACT BUCKET" column that makes the UI look like a real flow scanner is the most fictional part.

**Problem 3 — there is no learning loop.**
`db.close_signal()` just sets `status='closed'` and throws the outcome away. Nothing records entry→exit P&L, win/loss, which `flow_strategy` actually worked, or the conditions that preceded winners. Every "learn from trades / patterns / limitations / what worked" goal is **unbuilt**. The system has no memory of being right or wrong, so it cannot improve.

**Problem 4 — the credit bomb.**
`dashboard.py._auto_scan_loop` defaults to **every 1 minute**, spawns a full `claude -p` subprocess each time, with **no market-hours gate and no lock**. That's ~1,440 Claude CLI runs/day including nights and weekends, and manual scans can stack concurrently. This is the biggest silent credit drain. Directly contradicts the "reduce credits" goal.

**Also:** hardcoded `/Users/rohitlode/...` paths (CLI path `/usr/local/bin/claude`, MCP config path, a `sys.path.insert` to `tradingview-mcp/src`) — a machine rename breaks the engine silently. Unbounded log files. SQLite on default journal mode with background threads (lock/corruption risk). **Zero tests on code that decides money.**

**Bottom line:** the signal-quality + learning layer is ~25 wearing a 65 costume. Fix the costume first.

---

## 3. Phase 0 — Foundation (BUILD THIS FIRST)

Goal: build the scoreboard and stop the credit bleed, so every later change is measurable. All of it machine-agnostic. Owner approved doing all of 0.1–0.6 as one pass.

### 0.1 — `config.py` (kill hardcoded paths)
Create a central config sourced from env vars with safe defaults. Everything machine-specific goes here:
- `FLOWSCANNER_HOME` (default = repo dir), derived `DATA_DIR`, `LOGS_DIR`, `BACKUP_DIR`, `PROMPTS_DIR`, `REVIEWS_DIR` (create them on import).
- `CLAUDE_BIN` = `os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"` — never hardcode `/usr/local/bin/claude`.
- `MCP_CONFIG` (path to claude_desktop_config.json; empty ⇒ scans use the free local screener).
- `TV_MCP_SRC` (optional, for the direct news import in scanner.py).
- `AUTH_USER`/`AUTH_PASS`, `SCAN_INTERVAL_MIN` (default 5), `DAILY_CREDIT_CAP` (default 60), `MARKET_TZ` (default US/Eastern), `CLAUDE_TIMEOUT` (default 180).
- Helper `claude_available()`.
Then replace every hardcoded path in `dashboard.py`, `scanner.py`, `state.py`, `db.py`, and the prompts with config references.

### 0.2 — `guards.py` (defuse the credit bomb)
- `market_is_open(now=None)` — True only Mon–Fri, 09:30–16:00 in `MARKET_TZ`, excluding a small hardcoded holiday set. Use `zoneinfo`; fall back to naive local time if unavailable.
- **Daily credit budget**, counted in a new `credit_log` DB table: `credits_used_today()`, `budget_remaining()`, `record_credit(kind, detail)`, `can_spend_credit()`. Hard cap = `DAILY_CREDIT_CAP`.
- **`ScanLock`** context manager — single-flight file lock at `DATA_DIR/scan.lock`, raises `ScanLock.Busy` if held, auto-reclaims a stale lock (>300s). So auto + manual scans can never run two `claude -p` at once.

### 0.3 — `runner.py` (one guarded chokepoint for all scans)
`run_scan_once(trigger)` that, in order: acquire `ScanLock` → if Claude+MCP configured and budget remains, `record_credit()` **before** spawning `claude -p` (fail-safe, so a crash still counts) → on any failure/timeout/absent-MCP, fall back to `_direct_fallback()` which runs the free local `scanner.run_scan()` + `ingest()` (zero credits). Never raises; returns a human status string. Both `/scan` and the auto-loop call this — guards can't be bypassed.

### 0.4 — `db.py` hardening + the `outcomes` ledger (the heart of learning)
- In `get_conn()`: `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`, `timeout=5.0`.
- New table **`outcomes`**: `id, signal_id, ticker, opened_at, closed_at, entry_price, exit_price, quantity, contract_symbol, flow_strategy, direction, conviction_tier, test_bucket, stop, tp1, tp2, pnl_pct, pnl_abs, exit_reason, hold_minutes, is_win, features_json, status`. The `features_json` is the **full signal snapshot frozen at entry** — without it you can never ask "what did winners look like?".
- New table **`credit_log`**: `id, used_at, kind, detail`.
- Indexes on outcomes(status, flow_strategy), credit_log(used_at), signals(status, ticker).
- Rewrite **`ack_signal(signal_id, entry_price, quantity=None, stop=None, tp1=None, tp2=None)`**: set entry on the signal AND open an `outcomes` row with the frozen snapshot. Must be **idempotent** (don't open a 2nd open row for the same signal).
- Rewrite **`close_signal(signal_id, exit_price=None, exit_reason="manual")`**: finalize the outcome row with realized P&L. **P&L must be correct for short as well as long** — short profits when price falls: `pnl_pct = raw_pct if direction=="long" else -raw_pct`. Compute `pnl_abs`, `hold_minutes`, `is_win = 1 if pnl_pct>0 else 0`.
- Add `get_outcomes(status=None, limit)`, `get_winrate_by(field)` (group closed outcomes by flow_strategy / conviction_tier / ticker / test_bucket / direction → n, win_rate, avg_pnl_pct, total_pnl), and `backup_db()` (`VACUUM INTO data/backups/signals-<ts>.db`, keep last 14).

### 0.5 — Honest labels (stop the fiction)
- In `scanner.py._classify`: set `oi_behavior = None` (refuse to fabricate OI). The proxy may produce at most `WATCH` — it must **never** mint `VALIDATED_TEST` (reserve that name for real signal-level backtesting in Phase 2).
- Update `prompts/scan.md` / `analyze.md` to instruct Claude never to emit `VALIDATED_TEST` and to use a relative `ingest.py` path.
- Templates already render `—` for missing fields, so honest blanks just work.

### 0.6 — Wire it into `dashboard.py`
- Replace the duplicated subprocess blocks in `/scan` and `_auto_scan_loop` with `runner.run_scan_once(...)`.
- **Gate `_auto_scan_loop` behind `guards.market_is_open()`** and use `SCAN_INTERVAL_MIN` (≥60s floor). Outside market hours, sleep 5 min and re-check — zero overnight/weekend credits.
- Add a `_nightly_backup_loop` thread calling `db.backup_db()` once a day.
- Switch the scan log handler to `RotatingFileHandler` (logs are currently unbounded).
- Add **`/health`** (DB ping → 200/503 for watchdog/Tailscale) and enrich **`/status`** with `market_open`, `credits_used_today`, `credits_remaining`, `daily_credit_cap`, `scan_interval_min`.
- De-hardcode and budget-gate the `/analyze` route the same way.

### 0.7 — Tests (`tests/test_phase0.py`) — first tests on money code
Cover the invariants that silently cost money: ledger open/close, **P&L for long AND short**, `is_win`, ACK idempotency, win-rate aggregation, credit budget counting + cap, single-flight lock blocks a 2nd scan, market-hours weekend gate, and the honesty invariants (classifier never returns fabricated OI / never `VALIDATED_TEST`). Use a temp `FLOWSCANNER_HOME` so tests don't touch the real DB. Add `tests/conftest.py` to put repo root on `sys.path`. Make it runnable both via `pytest` and as a plain `python3 tests/test_phase0.py`.

### Phase 0 acceptance
- All modules import; `python3 tests/test_phase0.py` green.
- `curl localhost:8765/health` → ok; `/status` shows budget + market state.
- Auto-scan does nothing outside market hours; manual + auto cannot run concurrently.
- **Needle proof:** before/after `claude -p` count per trading day (from `credit_log`), and the first real win-rate number from `outcomes`. You now have a measurable "65".

### Phase 0 risk callout (tell the owner)
If `MCP_CONFIG` is unset, scans fall back to the **free local TradingView screener** instead of Claude. Set `MCP_CONFIG` to keep the Claude path. Also change the default `DASH_PASS`.

---

## 4. Later phases (do NOT start until Phase 0 gives you a metric)

**Phase 1 — Trustworthy capture & closed loop.**
- `exits.py`: a **deterministic Python** evaluator for the 8 exit conditions (stop, TP1, TP2, OI fade, premium decay ≤ −50%, DTE ≤ 3 + OTM, etc.). Exit math is arithmetic → zero credits, zero latency. Add `stop/tp1/tp2` to schema. Claude only narrates *why* on request.
- Position sync from IBKR / Robinhood MCP so Open Trades reflects reality, not just manual ACKs.
- **Weekly self-review**: a cron `claude -p` reads `outcomes`, writes a dated `reviews/YYYY-MM-DD.md` (win rate by strategy / tier / ticker / hold duration; what worked / what to stop). Once a week ⇒ nearly free. *This is the "learns patterns/limitations" deliverable.*
- **Needle:** does 🔥 HIGH actually out-win ⚡ MODERATE in `outcomes`? If tiers don't separate, conviction is noise → rework it.

**Phase 2 — Make predictions actually good** (only after Phase 1 ground truth).
- Signal-level backtesting that replays the *real* rule on history → `VALIDATED_TEST` finally earns its name.
- Conviction weights *learned* from `outcomes` (logistic regression on entry features → P(win); tiny, interpretable, retrains weekly).
- Latency/credits: local screener pre-filters 750→top-8 *before* any Claude call; expensive `combined_analysis` runs on ≤5 finalists only.

**Phase 3 — Highly available & boring.**
Watchdog on `/health`; structured JSON logging; Claude timeout + retry w/ backoff; Slack-MCP alerts on scan failure / budget breach / DB lock; expand the test suite.

**Phase 4 — Real options flow (GATED).**
Only when calibration proves the engine is genuinely good — concrete bar: **≥55% win rate over ≥30 logged trades, with tiers separating.** Then wire IBKR `search_contracts` for real DTE/OTM/OI first (free, already connected), Unusual Whales last. Real sweep data *replaces* the volume proxy as trigger; volume scan becomes confirmation. Only here do the empty OI/DTE cells become real instead of honestly blank.

---

## 5. "Prompts / skills / .md / babysitting — which?" — the answer

- **Deterministic Python** for anything that's math (exits, P&L, pre-filter) → free, instant, testable.
- **`claude -p` + `.md` prompts** only for *judgment* (scan classification, weekly review).
- **cron** for the babysitting (market-hours scan cadence, weekly review, nightly backup).
- **A `/flowscan` skill** so the owner can drive it conversationally.

Rule of thumb that enforces 65→66: **if a task is arithmetic, never spend a credit on it.**

---

## 6. Hard constraints for whoever executes this

- Python **3.9** — use `from __future__ import annotations` for modern type hints.
- Keep it lightweight — SQLite + threads + launchd. No external services, no microservices, no message queues. The owner explicitly rejected the heavy 17-unit design.
- **Sequence is non-negotiable:** Phase 0 → 1 before anything else. Phases 2–4 are real 65→66 moves *only after* the scoreboard exists to prove they moved it.
- Never re-introduce fabricated data to make the UI look fuller. An honest blank beats a wrong number when money is on the line.
- This is a personal-money repo on a personal machine; the owner pushes / opens the PR.
