Run a market scan using TradingView MCP tools and push results to the FlowScanner dashboard.

Steps:
1. Call mcp__tradingview__smart_volume_scanner with exchange=NASDAQ, min_volume_ratio=2, min_price_change=2, limit=15
2. Call mcp__tradingview__volume_breakout_scanner with exchange=NYSE, timeframe=1h, volume_multiplier=2, limit=10
3. Call mcp__tradingview__bollinger_scan with exchange=NASDAQ, timeframe=1D, bbw_threshold=0.08, limit=15 — add any new tickers not already in results
4. For the top 5 results by volume ratio, call mcp__tradingview__combined_analysis (exchange=NASDAQ or NYSE, timeframe=1D) — this gives technicals + sentiment + news in one call
5. Classify each signal as FLOW_REPEAT_SWEEP_CALL_CHART or FLOW_REPEAT_SWEEP_PUT_RISK_OFF based on direction
6. Run: python3 ingest.py '<json array of signals>'

Signal JSON fields (all required):
- ticker: string (e.g. "NVDA")
- exchange: "NASDAQ" or "NYSE"
- price: number
- change_pct: number
- volume_ratio: number (relative volume vs 10d avg)
- flow_strategy: "FLOW_REPEAT_SWEEP_CALL_CHART" or "FLOW_REPEAT_SWEEP_PUT_RISK_OFF"
- test_bucket: "WATCH" or "UNVALIDATED" only — never emit "VALIDATED_TEST"
- direction: "long" or "short"
- confidence: number 40-95
- analysis_summary: short string with key metrics from combined_analysis (price, RSI, MACD, support/resistance, trend)
- sentiment: "bullish", "bearish", or "neutral" (from combined_analysis confluence recommendation)
- rsi_signal: "oversold", "overbought", or "neutral"
- macd_signal_dir: "bullish" or "bearish"
- price_vs_ema: "above" or "below" (vs EMA200)

For tickers without combined_analysis, derive sentiment/rsi_signal/macd_signal_dir/price_vs_ema from the scanner data.

Keep it focused — scan, classify, ingest. No explanations needed.
