Analyze a single ticker using TradingView MCP tools and push to FlowScanner.

Ticker: {TICKER}

Steps:
1. Call mcp__tradingview__combined_analysis for {TICKER} on NASDAQ, timeframe=1D
   — this returns technicals + Reddit sentiment + news in one call
2. Call mcp__tradingview__multi_timeframe_analysis for {TICKER} on NASDAQ
   — for multi-TF confirmation (weekly → daily → 4H → 1H)
3. Classify signal: FLOW_REPEAT_SWEEP_CALL_CHART or FLOW_REPEAT_SWEEP_PUT_RISK_OFF
4. Run: python3 /Users/rohitlode/flowscanner/ingest.py '<json>'

Signal JSON fields:
- ticker, exchange, price, change_pct, volume_ratio
- flow_strategy: "FLOW_REPEAT_SWEEP_CALL_CHART" or "FLOW_REPEAT_SWEEP_PUT_RISK_OFF"
- test_bucket: "UNVALIDATED" (backtester overrides)
- direction: "long" or "short"
- confidence: 40-95
- analysis_summary: key metrics — price, RSI, MACD crossover, support/resistance levels, trend state, confluence verdict
- sentiment: "bullish", "bearish", or "neutral" (from combined_analysis confluence)
- rsi_signal: "oversold", "overbought", or "neutral"
- macd_signal_dir: "bullish" or "bearish"
- price_vs_ema: "above" or "below" (vs EMA200)

Keep it focused — analyze, classify, ingest. No explanations needed.
