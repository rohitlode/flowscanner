# FlowScanner — Handoff Document
**Generated:** 2026-06-10  
**Built for:** Rohit — active retail trader, Seattle (US/Pacific)  
**Project path:** `/Users/rohitlode/flowscanner/`  
**Dashboard:** `http://localhost:8765`

---

## The Photo That Started This

Rohit shared a photo of a friend's proprietary trading scanner dashboard. It showed a dark-themed web UI with tabs: **Scanner | Open Trades | Flow Trades | Report | Analytics(BT) | Pipeline | Market Plan**.

The **Flow Trades tab** (the primary view) had these columns:
- **SYMBOL** — ticker + specific option contract (e.g. `$575P Jul17`) + live premium (`now $32.02 entry $27.47`)
- **FLOW STRATEGY** — green badge: `FLOW_REPEAT_SWEEP_CALL_CHART` or `FLOW_REPEAT_SWEEP_PUT_RISK_OFF`
- **TEST BUCKET** — green badge: `VALIDATED_TEST`
- **CONTRACT BUCKET** — `31-60 DTE | 3-7% OTM | QUALITY 22D PLUS CONTRACT | OI FADING 17,697→15,962 (-1,735)`
- **DATE/TIME EST**

Toolbar: **Scan Now | Auto: On | Every 1 min ▾ | Check Exits** · "Scanning ~750 candidates fetching live Yahoo prices"

Real examples from the photo:
- SMH `$575P Jul17` — FLOW_REPEAT_SWEEP_PUT_RISK_OFF — VALIDATED_TEST — 31-60 DTE | 3-7% OTM | QUALITY 22D PLUS
- AAPL `$275P Aug21` — FLOW_REPEAT_SWEEP_PUT_RISK_OFF — VALIDATED_TEST — 61+ DTE | 3-7% OTM | QUALITY 22D PLUS
- GLD `$370P Jul17` — FLOW_REPEAT_SWEEP_PUT_RISK_OFF — VALIDATED_TEST — OI FADING 17,697→15,962 (-1,735)
- SNOW `$250C Jan15` — FLOW_REPEAT_SWEEP_CALL_CHART — VALIDATED_TEST — 61+ DTE | OI HOLDING 2,373→2,356 (-17)
- UNH `$410C Jul17` — FLOW_REPEAT_SWEEP_CALL_CHART — VALIDATED_TEST — 31-60 DTE | OI STUCK UP 1,891→3,479 (+1,588)

The goal: **build a lightweight version of this using Claude Code's existing MCP tools**, no heavy architecture, no external services beyond what's already connected.

---

## Why We Chose This Architecture (vs the Heavy One)

There is a separate document `HANDOFF_COMPLETE_v2.md` (Rohit's Downloads) that describes a fully-specified production system with 17 units, APScheduler, Alembic migrations, a custom `tradingview_client.py`, etc.

**We did not build that.** The reason: Claude Code already has 27 TradingView MCP tools, IBKR MCP, and Robinhood MCP connected. The heavy system was designed before anyone realized these MCPs existed in the Claude Code session.

**Key insight:** Claude Code IS the scanner. The MCPs are not available to a standalone Python process — they're available to Claude Code at runtime. So the architecture is:

```
Claude Code (scanner)          FastAPI dashboard (reader)
  ├── calls TradingView MCPs      ├── reads SQLite
  ├── classifies signals          ├── serves HTMX UI
  └── python3 ingest.py <json>    └── buttons POST to routes
                     ↓                       ↑
              SQLite (bridge)  ←─────────────┘
```

Rohit runs a scan by telling Claude Code: "run a scan" or "scan for signals". Claude calls the MCPs, classifies results, and pushes to SQLite. The dashboard auto-refreshes every 30s.

---

## MCPs in Use

### TradingView MCP (27 tools via `mcp__tradingview__*`)
The primary scanner. Key tools:

| Tool | Used For |
|------|----------|
| `smart_volume_scanner` | Candidate universe — finds volume spikes (≥2x avg) + price move (≥2%) on NASDAQ/NYSE. **This is the flow substitute.** |
| `volume_breakout_scanner` | Secondary scan — price + volume breakout confirmation |
| `multi_agent_analysis` | Per-symbol: 3-agent debate (Technical / Sentiment / Risk) → final verdict + net score |
| `combined_analysis` | POWER TOOL — TradingView technicals + Reddit sentiment + financial news in one call |
| `volume_confirmation_analysis` | Deep per-symbol volume analysis |
| `multi_timeframe_analysis` | Weekly→Daily→4H→1H→15m alignment |
| `top_gainers` / `top_losers` | Quick universe scan |
| `yahoo_price` | Live price quotes |
| `market_sentiment` | Reddit sentiment per ticker |
| `bollinger_scan`, `rating_filter` | Additional filters |

**Exchange support:** NASDAQ, NYSE (stocks) + KUCOIN, BINANCE etc (crypto).

### IBKR MCP (`mcp__claude_ai_Interactive_Brokers_IBKR__*`)
Used for account data and (eventually) options chain. Key tools:
- `get_account_positions` — open positions
- `get_price_snapshot` — live price per symbol
- `search_contracts` — option chain lookup (DTE, strike, OTM%)
- `get_account_orders` — pending orders

### Robinhood MCP (`mcp__claude_ai_Robinhood__*`)
- `get_equity_positions` — Robinhood holdings
- `get_equity_quotes` — live quotes
- `get_portfolio` — portfolio summary

### How Signal Classification Works (Flow Strategy substitute)

Since we don't have a real options sweep feed, we approximate:

```
smart_volume_scanner hit (volume ≥2x, price move ≥2%)
        ↓
multi_agent_analysis → net_score
        ↓
PUT_RISK_OFF:  bearish momentum + large cap index/hedge name (SPY,QQQ,SMH,AAPL,GLD etc)
               OR all 3 agents bearish + RSI falling
CALL_CHART:    bullish RSI + MACD bullish crossover + agents agree BUY
        ↓
test_bucket from net_score:
  net_score ≥ 3  → VALIDATED_TEST
  net_score 1-2  → WATCH
  net_score ≤ 0  → UNVALIDATED
```

Contract bucket fields (DTE, OTM%, OI behavior) are currently **estimated** — see "What Needs To Be Done" below.

---

## What's Built (Done)

### Files
```
flowscanner/
├── dashboard.py       FastAPI app — routes, HTMX responses
├── db.py              SQLite init + upsert_signal + get_signals + scan_run logging
├── state.py           File-based flags: auto_enabled, scan_requested, exit_check_requested
├── ingest.py          CLI script: python3 ingest.py '<json array>' → writes to SQLite
├── requirements.txt   fastapi, uvicorn, jinja2, python-multipart
├── data/
│   ├── signals.db     SQLite database
│   └── state.json     Button state flags
├── logs/
│   ├── dashboard.log
│   └── dashboard.err
└── templates/
    ├── base.html               Dark theme, nav, badge styles, HTMX CDN
    ├── flow_trades.html        Main tab — toolbar + table + 30s HTMX polling
    ├── scanner.html            Scan runs history
    ├── open_trades.html        Positions with entry price
    └── partials/
        └── signal_rows.html   Reusable table rows partial
```

### Routes
| Method | Path | Does |
|--------|------|------|
| GET | `/` | Redirects to `/flow-trades` |
| GET | `/flow-trades` | Full Flow Trades page |
| GET | `/flow-trades/rows` | HTMX partial — polled every 30s |
| GET | `/scanner` | Scan run history |
| GET | `/open-trades` | Positions with entry_price set |
| POST | `/scan` | Sets `scan_requested=true` in state.json, returns inline confirmation |
| POST | `/check-exits` | Sets `exit_check_requested=true`, returns inline confirmation |
| POST | `/auto-toggle` | Toggles auto flag, re-renders button with new label/color |
| GET | `/status` | JSON: auto state, signal count, pending flags |

### Auto-restart (launchd)
Service plist at `~/Library/LaunchAgents/com.rohit.flowscanner.plist`.  
Starts on login, restarts on crash.

```bash
launchctl load ~/Library/LaunchAgents/com.rohit.flowscanner.plist    # start
launchctl unload ~/Library/LaunchAgents/com.rohit.flowscanner.plist  # stop
launchctl list | grep flowscanner                                      # check
tail -f ~/flowscanner/logs/dashboard.log                              # logs
```

### Signals DB Schema
```sql
signals (
  id, created_at, ticker, exchange, price, change_pct, volume_ratio,
  flow_strategy, test_bucket,
  dte_bucket, otm_pct_range, contract_quality, oi_behavior,
  oi_prev, oi_curr, oi_delta,
  contract_symbol, entry_price, now_price,
  direction, confidence, analysis_summary, status
)

scan_runs (id, started_at, candidates, signals_found, exchange, status)
```

### Running a Scan (Current Flow)
Tell Claude Code: **"run a scan"**. Claude will:
1. Call `smart_volume_scanner` on NASDAQ + `volume_breakout_scanner` on NYSE
2. Filter top candidates by volume ratio, price change, RSI
3. Run `multi_agent_analysis` or `combined_analysis` on each
4. Classify into CALL_CHART or PUT_RISK_OFF + assign test_bucket
5. Build JSON payload and run `python3 ingest.py '<json>'`
6. Dashboard auto-refreshes within 30s

---

## What Needs To Be Done (Priority Order)

### P1 — Real Options Contract Data
**Problem:** DTE bucket, OTM%, OI behavior, contract_symbol are currently estimated/hardcoded at ingest time. They need to come from a real options chain.

**Solution:** Use IBKR MCP `search_contracts` tool:
```
search_contracts(symbol="AGL", secType="OPT", exchange="SMART")
→ returns contracts with strike, expiry, right (C/P)
→ compute DTE from expiry, OTM% from current price vs strike
→ poll OI over time to get STUCK_UP / FADING / HOLDING
```

OI history needs to be stored between polls (add `oi_snapshots` table to db.py) to compute delta.

### P2 — Real Scan Trigger from Button
**Problem:** "Scan Now" button sets a flag in state.json but nothing actually watches that flag and runs a scan automatically. Rohit has to tell Claude manually.

**Solution:** Add a `/loop` skill invocation that polls `state.scan_requested()` every 60s during market hours and triggers the scan pipeline if true.

Alternatively: write a `scanner_runner.py` that Claude Code runs via `/loop 1m` during market hours — it checks the flag and calls back into Claude Code via a scheduled prompt.

### P3 — Exit Check Logic
**Problem:** "Check Exits" button sets a flag but no exit logic runs.

**Exit conditions to implement** (from HANDOFF_COMPLETE_v2):
1. Price ≤ stop → EXIT_STOP
2. Price ≥ TP1 → EXIT_TP1
3. Price ≥ TP2 → EXIT_TP2
4. OI FADING on held call → EXIT_OI_FADE
5. Premium decay ≤ -50% → EXIT_PREMIUM_DECAY
6. DTE ≤ 3 + OTM → EXIT_DTE_DECAY

Needs `entry_price`, `stop`, `tp1`, `tp2` populated on ACK — currently `entry_price` is set but stop/tp fields don't exist in schema yet.

### P4 — ACK Flow (Open Trades)
Currently Open Trades tab shows signals where `entry_price` is set. There's no ACK button on the dashboard to actually mark a signal as entered. Need:
- ACK button per signal row in flow_trades
- Modal/inline form: entry price + quantity
- POST `/ack/{signal_id}` → updates entry_price, moves to Open Trades

### P5 — Auto Scan Scheduling
Wire the "Every N min" dropdown to actually schedule recurring scans. Use APScheduler or `/loop` skill. Currently the dropdown is cosmetic.

---

## Future Enhancements

### Real Options Flow Feed
The biggest gap vs the original system. The friend's scanner uses actual options sweep data (institutional block trades, repeat sweeps). Our substitute (volume spike + multi_agent_analysis) is an approximation.

Options:
- **Unusual Whales API** — paid, ~$50/mo, gives real sweep data with ticker, strike, expiry, premium, side
- **Market Chameleon** — free tier available
- **IBKR real-time flow** — possible via IBKR MCP if the account has market data subscriptions

When a real flow feed is added: replace `smart_volume_scanner` as the trigger and use actual sweep classification for `flow_strategy`. Volume scan becomes a secondary confirmation.

### VALIDATED_TEST Scoring (Strategy Performance Table)
The original system tracks whether each flow strategy (CALL_CHART, PUT_RISK_OFF) historically wins. When trades are closed, update a `strategy_performance` table. After N signals, compute win rate. If win_rate ≥ 55% → VALIDATED_TEST, 45-55% → WATCH, else UNVALIDATED.

Currently `test_bucket` is set heuristically from multi_agent_analysis net_score. Replace with real historical classification once enough trades accumulate.

### Pipeline Tab (Funnel Visualization)
Show drop-off at each stage:
```
candidates [38] → volume filter [15] → deep analysis [8] → confidence pass [3] → alerted [3]
```
Data already available in `scan_runs` table (add per-stage counts to schema).

### Analytics (BT) Tab
Backtest tab showing per-strategy win rate, equity curve, avg return. Requires closed trades with P&L recorded.

### Market Plan Tab
Scenario-based planning: "If SPY holds $X → look for entries in Y". Manual entry with triggered/not-triggered status. Low complexity, high value for Rohit's morning prep.

### Slack / Pushover Alerts
When a new signal is ingested → push to Slack webhook + Pushover. HANDOFF_COMPLETE_v2 has full spec. Add `slack_status` / `pushover_status` columns to signals table.

### IBKR Position Sync
Currently Open Trades are only signals where `entry_price` was manually set. Auto-populate by syncing IBKR `get_account_positions` on startup — match positions to signals by ticker.

---

## Accounts Context (Rohit's Setup)

| Account | ID | Holdings | Notes |
|---|---|---|---|
| Robinhood Margin | 981589211 | TSLA AAPL META NVDA AMD HOOD GRAB LMND LULU JEPI IAU EVLV NOW CAMT NVT CGNX + options | PDT applies |
| Robinhood IRA | 891856684 | SCHD XLE O META ABBV | No margin, options L1 |
| IBKR Swing | — | DRAM NASA NOK NOW NUAI NVDA SNOU ZETA | No PDT |

Trade horizons: 0DTE · intraday · swing (3-15d) · LEAPS (3-5yr)  
Risk per trade: $500 (1% of ~$50K)

PUT_RISK_OFF tickers to watch (institutional hedges): SPY QQQ IWM DIA XLK AAPL MSFT NVDA AMZN GOOGL META SMH GLD

---

## Quick Start for Next Claude

```bash
# 1. Dashboard already running at http://localhost:8765 (launchd managed)
# 2. Check it's alive:
curl http://localhost:8765/status

# 3. Run a scan (say this to Claude Code):
#    "run a scan" or "scan NASDAQ for signals"

# 4. Manual ingest:
cd /Users/rohitlode/flowscanner
python3 ingest.py '[{"ticker":"NVDA","exchange":"NASDAQ","price":135.20,...}]'

# 5. Check state flags:
cat data/state.json

# 6. View logs:
tail -f logs/dashboard.log
```

**When Rohit says "run a scan":**
1. Call `mcp__tradingview__smart_volume_scanner` (NASDAQ, min_volume_ratio=2, min_price_change=2)
2. Call `mcp__tradingview__volume_breakout_scanner` (NYSE, 1h, volume_multiplier=2)
3. Filter: price > $3, volume > 50k, ignore penny stocks
4. For top 3-5 hits: call `mcp__tradingview__multi_agent_analysis` per symbol
5. Classify flow_strategy + test_bucket (see classification logic above)
6. Run `python3 /Users/rohitlode/flowscanner/ingest.py '<json>'`
7. Confirm to Rohit: "X signals ingested, dashboard updated at http://localhost:8765"
