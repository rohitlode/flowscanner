Analyze a single ticker using TradingView MCP tools and push to FlowScanner.

Ticker: {TICKER}

Steps:
1. Call mcp__tradingview__multi_timeframe_analysis for {TICKER} on NASDAQ
2. Call mcp__tradingview__multi_agent_analysis for {TICKER} on NASDAQ, timeframe=1h
3. Call mcp__tradingview__financial_news for {TICKER}, category=stocks, limit=3
4. Classify signal: FLOW_REPEAT_SWEEP_CALL_CHART or FLOW_REPEAT_SWEEP_PUT_RISK_OFF
5. Run: python3 /Users/rohitlode/flowscanner/ingest.py '<json>'

Signal JSON fields: ticker, exchange, price, change_pct, volume_ratio, flow_strategy, test_bucket, direction, confidence, analysis_summary, sentiment

Keep it focused — analyze, classify, ingest. No explanations needed.
