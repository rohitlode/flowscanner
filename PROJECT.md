# FlowScanner — Project Journal

> **For Claude:** Read this before making any changes. Update the status of todos when you complete them. Add new decisions and todos as they arise. This is the source of truth for project state.

## Governing Rule
"If this system is 65, adding something should make it 66, not 64."
Every change must move a measured number up. The Needle Test: Hypothesis / Measurement / Cost / Kill condition.

---

## Architecture (current)

```
Claude Code (scanner)              FastAPI dashboard (reader)
  ├── TradingView MCP tools          ├── reads SQLite
  ├── IBKR MCP tools (flow data)     ├── HTMX dark-theme UI
  ├── classifies signals             └── buttons POST to routes
  └── python3 ingest.py '<json>'
                    ↓
             SQLite (data/signals.db)
```

| File | What it does |
|---|---|
| `config.py` | All paths + env vars. Single source of truth — no hardcoded paths anywhere else |
| `guards.py` | market_is_open(), ScanLock (single-flight), daily credit budget |
| `runner.py` | Single guarded chokepoint for all scans — acquires lock, checks budget, falls back to direct scan |
| `dashboard.py` | FastAPI routes + HTMX responses + auto-scan background thread |
| `db.py` | SQLite schema, signal upsert/query, outcomes ledger, credit_log |
| `scanner.py` | Direct TradingView screener + yfinance analysis + signal classification |
| `conviction.py` | 🔥 HIGH / ⚡ MODERATE / 📊 NO FLOW tiers + sizing. Now calls ibkr_flow.py when ibkr_data present |
| `ibkr_flow.py` | Scores real IBKR call/put volume data into flow_score (0-4) for conviction enrichment |
| `ingest.py` | CLI: python3 ingest.py '<json>' → writes signals to DB |
| `backtester.py` | MACD/RSI/VolBreakout backtests on 1y daily OHLCV (proxy only — see Phase 2) |
| `state.py` | File-based flags (auto on/off, scan_requested, interval) |
| `prompts/scan.md` | Claude scan prompt — includes step 4b for IBKR options flow pull |
| `prompts/analyze.md` | Claude analyze prompt — includes step 2b for IBKR options flow pull |

---

## Project Decisions Log

### 2026-06-11 — Initial build
- FastAPI + HTMX + SQLite (no React, no microservices — owner explicitly lightweight)
- TradingView MCP via `claude -p` headless (not direct API calls for scan classification)
- Conviction tiers as proxy for options flow (no UW API key yet)

### 2026-06-12 — Phase 0
- `config.py` centralizes all paths (machine rename was a silent failure mode)
- Outcomes ledger added (no learning without recording wins/losses)
- `VALIDATED_TEST` banned from classifier (was fabricating institutional-grade labels)
- `oi_behavior` set to None (price vs EMA is not OI — was fictional)
- Market hours gate on auto-scan (was burning ~1,440 credits/day overnight)
- Daily credit cap: 60 (configurable via `DAILY_CREDIT_CAP` env var)

### 2026-06-12 — Phase 0.5 — IBKR options flow wired into conviction
- **Decision:** wire IBKR real call/put volume into conviction scoring for all signals
- **Why:** proxy (volume_ratio + technicals) has no options information. IBKR is already connected, free, no API key needed
- **Design:** `ibkr_flow.py` scores call/put ratio + volume vs avg + IV percentile → flow_score 0-4 added to conviction
- **Guard:** outside RTH volume=0 → skip enrichment, fall back to proxy label "(proxy — wire IBKR flow for confirmation)"
- **When confirmed:** label suffix becomes "(IBKR flow confirmed)"
- **TODO:** replace with Unusual Whales sweep detection when API key obtained (see Phase 4)

---

## Phases

### Phase 0 — Foundation ✅ COMPLETE (2026-06-12)
- [x] `config.py` — kill hardcoded paths
- [x] `guards.py` — market hours gate + ScanLock
- [x] `runner.py` — single guarded scan chokepoint
- [x] Outcomes ledger — records every ACK'd trade with frozen features_json
- [x] `close_signal()` — correct P&L for long AND short
- [x] `credit_log` — daily budget, default 60/day
- [x] Honest labels — oi_behavior=None, no VALIDATED_TEST from classifier
- [x] `/health` endpoint
- [x] `/status` enriched with market/credit fields
- [x] RotatingFileHandler — logs no longer unbounded
- [x] 15/15 tests passing

### Phase 0.5 — IBKR Options Flow 🔄 IN PROGRESS (2026-06-12)
- [x] `ibkr_flow.py` — `score_ibkr_flow()` using real call/put ratio + volume vs avg + IV percentile
- [x] `conviction.py` — uses ibkr_data if present, falls back to proxy
- [x] `prompts/scan.md` — step 4b instructs Claude to pull IBKR data for each signal
- [x] `prompts/analyze.md` — step 2b instructs Claude to pull IBKR data for ticker
- [x] `runner.py` — IBKR search_contracts + get_price_snapshot added to allowedTools
- [x] `dashboard.py` — same IBKR tools added to /analyze allowedTools

### Phase 1 — Trustworthy Capture & Closed Loop 📋 TODO
Prerequisites: ~20 closed outcomes in DB across 2-3 weeks of trading.
- [ ] `exits.py` — deterministic Python exit evaluator (8 conditions: stop, TP1, TP2, OI fade, premium decay ≤-50%, DTE ≤3+OTM, etc.). Zero credits — arithmetic only.
- [ ] Position sync from IBKR/Robinhood MCP — open trades reflects reality, not just manual ACKs
- [ ] Weekly self-review — cron `claude -p` reads outcomes, writes `reviews/YYYY-MM-DD.md` (win rate by strategy/tier/ticker/hold duration). Once a week = nearly free.
- [ ] **Needle:** does 🔥 HIGH actually out-win ⚡ MODERATE in outcomes? If tiers don't separate, conviction is noise → rework it.

### Phase 2 — Make Predictions Actually Good 📋 TODO
Prerequisites: Phase 1 complete + ≥30 closed trades with tier separation.
- [ ] Signal-level backtesting — replay the real rule on history → VALIDATED_TEST finally earns its name
- [ ] Conviction weights learned from outcomes (logistic regression on entry features → P(win))
- [ ] Local screener pre-filters 750→top-8 before any Claude call (latency + credit optimization)
- [ ] Expensive combined_analysis runs on ≤5 finalists only

### Phase 3 — Highly Available & Boring 📋 TODO
- [ ] Watchdog on /health
- [ ] Structured JSON logging
- [ ] Claude timeout + retry with backoff
- [ ] Slack-MCP alerts on scan failure / budget breach / DB lock
- [ ] Expand test suite

### Phase 4 — Real Options Flow (GATED) 📋 TODO
**Gate: ≥55% win rate over ≥30 logged trades, with conviction tiers separating**
- [ ] IBKR `search_contracts` for real DTE/OTM/OI per signal (currently blank in DB)
- [ ] Unusual Whales API — sweep alerts, flow, OI changes (requires paid API key)
  - Endpoint: `/api/option-trades/flow-alerts`
  - Replaces IBKR call/put volume proxy as primary flow signal
  - IBKR becomes confirmation layer
- [ ] Real sweep data replaces volume proxy as trigger; volume scan becomes confirmation
- [ ] Fill `dte_bucket`, `otm_pct_range`, `contract_quality`, `oi_prev/curr/delta` columns (all NULL today)

---

## Known Limitations (honest blanks > wrong numbers)
- `oi_behavior` — always NULL. Real OI requires options data (Phase 4).
- `dte_bucket`, `otm_pct_range`, `contract_quality`, `oi_prev/curr/delta` — always NULL. Phase 4.
- `VALIDATED_TEST` — reserved for Phase 2 signal-level backtesting. Classifier caps at WATCH.
- `conviction_tier` — proxy mode outside RTH (IBKR flow data is zero when market closed).
- `sentiment` field — from Reddit via TradingView MCP. Often 0 posts (rate limited).
- `now_price` on open trades — refreshed via yfinance on page load only, not streaming.
- Auto-scan — only fires during market hours (9:30-16:00 ET). Manual scan works anytime.
- IBKR options flow — enriches conviction during RTH only. Outside RTH: call_volume_today=0 → ibkr_available=False → proxy fallback.

---

## Credit Budget
- Default: 60 Claude CLI calls/day (`DAILY_CREDIT_CAP` env var)
- Each scan = 1 credit (recorded before spawn, fail-safe)
- Each analyze = 1 credit
- Auto-scan: only during market hours, interval from `SCAN_INTERVAL_MIN` (default 5 min)
- Max theoretical: ~78 auto-scans/day during market hours (6.5h × 12/h) — well under 60 cap at 5min interval
- Direct TradingView screener fallback = 0 credits

---

## Metrics to Watch

Run this to check progress toward Phase 1:
```sql
SELECT conviction_tier, COUNT(*) as n, ROUND(AVG(is_win)*100,1) as wr, ROUND(AVG(pnl_pct),2) as avg_pnl
FROM outcomes WHERE status='closed'
GROUP BY conviction_tier;
```

Run this when you have ≥20 trades to decide if Phase 1 is ready:
```sql
SELECT flow_strategy, conviction_tier, COUNT(*) as n, ROUND(AVG(is_win)*100,1) as wr
FROM outcomes WHERE status='closed'
GROUP BY flow_strategy, conviction_tier
ORDER BY wr DESC;
```

---

## Environment
- Machine: Rohit's MacBook Pro
- Dashboard: http://localhost:8765 (Tailscale: https://rohits-macbook-pro.taild8fd40.ts.net/)
- Auth: `DASH_USER`/`DASH_PASS` env vars (set in launchd plist)
- Python: 3.9 (Apple system python at /Library/Developer/CommandLineTools/...)
- Claude CLI: `/usr/local/bin/claude` (`CLAUDE_BIN` env var)
- MCP config: `~/Desktop/claude/config/claude_desktop_config.json` (`MCP_CONFIG` env var)
- TradingView MCP src: `~/Projects/tradingview-mcp/src` (`TV_MCP_SRC` env var)
- launchd plist: `~/Library/LaunchAgents/com.rohit.flowscanner.plist`
- Repo: https://github.com/rohitlode/flowscanner
