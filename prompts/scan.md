Run a market scan using TradingView MCP tools and push results to the FlowScanner dashboard.

Steps:
1. Call mcp__tradingview__smart_volume_scanner with exchange=NASDAQ, min_volume_ratio=2, min_price_change=2, limit=15
2. Call mcp__tradingview__volume_breakout_scanner with exchange=NYSE, timeframe=1h, volume_multiplier=2, limit=10
3. For the top 3 results by volume ratio, call mcp__tradingview__multi_timeframe_analysis to confirm alignment
4. Classify each signal as FLOW_REPEAT_SWEEP_CALL_CHART or FLOW_REPEAT_SWEEP_PUT_RISK_OFF based on direction
5. Run: python3 /Users/rohitlode/flowscanner/ingest.py '<json array of signals>'

Signal JSON fields (all required):
- ticker: string (e.g. "NVDA")
- exchange: "NASDAQ" or "NYSE"
- price: number
- change_pct: number
- volume_ratio: number (relative volume vs 10d avg)
- flow_strategy: "FLOW_REPEAT_SWEEP_CALL_CHART" or "FLOW_REPEAT_SWEEP_PUT_RISK_OFF"
- test_bucket: "UNVALIDATED" (always use this — backtester will override)
- direction: "long" or "short"
- confidence: number 40-95
- analysis_summary: short string with key metrics
- sentiment: "bullish", "bearish", or "neutral"
- rsi_signal: "oversold", "overbought", or "neutral"
- macd_signal_dir: "bullish" or "bearish"
- price_vs_ema: "above" or "below"

Keep it focused — scan, classify, ingest. No explanations needed.
