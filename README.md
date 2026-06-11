# FlowScanner

A lightweight trading signal scanner dashboard inspired by institutional options flow tracking. Built with FastAPI + HTMX + TradingView MCP.

## What it does

- Scans NASDAQ + NYSE for unusual volume / price breakouts via TradingView screener
- Runs Claude CLI with TradingView MCP tools for deep multi-timeframe analysis
- Backtests MACD / RSI / Volume Breakout strategies on each ticker (1y daily OHLCV)
- Scores conviction tiers (🔥 HIGH / ⚡ MODERATE / 📊 NO FLOW) as a proxy for options flow
- Auto-scans on configurable interval (1 / 5 / 15 min) when Auto mode is on
- Accessible remotely via Tailscale Funnel (HTTPS)

## Stack

- **Backend**: FastAPI + Uvicorn (Python 3.9+)
- **Frontend**: HTMX + Jinja2 templates (dark theme, no React)
- **Data**: SQLite (`data/signals.db`)
- **Market data**: TradingView screener API + yfinance
- **AI scan**: Claude CLI headless mode with TradingView MCP (`--mcp-config`)
- **Auth**: HTTP Basic
- **Hosting**: launchd (auto-restart) + Tailscale Funnel (HTTPS)

## Setup

```bash
pip install -r requirements.txt
python dashboard.py
```

Dashboard runs at `http://localhost:8765` (user/pass set via `DASH_USER` / `DASH_PASS` env vars).

### Claude MCP scan (optional but recommended)

Install [Claude Code CLI](https://claude.ai/code) and configure `claude_desktop_config.json` with the TradingView MCP server. The dashboard will use it automatically when you click **Scan Now**.

## Tabs

| Tab | Description |
|-----|-------------|
| Flow Trades | Live signal feed with filters (strategy / conviction / bucket / vol / date) |
| Scanner | Scan history + live log monitor |
| Analytics | Backtest results with filter/sort |
| Open Trades | Signals with an entry price set |
| Pipeline | Scan run history |
| Report | Aggregate stats |

## Conviction Tiers (proxy mode)

Until Unusual Whales options flow is wired in, conviction is scored from volume ratio, backtest quality, MACD/RSI alignment, and AH fade detection:

| Tier | Criteria | Sizing |
|------|----------|--------|
| 🔥 HIGH | vol >2.5x + VALIDATED_TEST + no AH fade | FULL SIZE |
| ⚡ MODERATE | vol 1.5–2.5x OR WATCH bucket | HALF SIZE |
| 📊 NO FLOW | vol <1.5x or micro-cap | QUARTER SIZE |
| ⚠ AH FADE | gave back >50% of day gain after-hours | DO NOT ENTER |

Upgrades automatically when Unusual Whales sweep data is wired in.

## Roadmap

- [ ] Unusual Whales API for real options sweep data
- [ ] ACK flow — mark entry price on signals
- [ ] Exit check logic (8 conditions)
- [ ] P&L tracking on open trades
