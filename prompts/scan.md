<!-- allowedTools: mcp__tradingview__smart_volume_scanner, mcp__tradingview__volume_breakout_scanner, mcp__tradingview__bollinger_scan, mcp__tradingview__combined_analysis, mcp__tradingview__multi_timeframe_analysis, mcp__claude_ai_Interactive_Brokers_IBKR__search_contracts, mcp__claude_ai_Interactive_Brokers_IBKR__get_price_snapshot, Bash -->

Run a market scan using TradingView MCP tools and push results to the FlowScanner dashboard.

Steps:
1. Call mcp__tradingview__smart_volume_scanner with exchange=NASDAQ, min_volume_ratio=2, min_price_change=2, limit=15
2. Call mcp__tradingview__volume_breakout_scanner with exchange=NYSE, timeframe=1h, volume_multiplier=2, limit=10
3. Call mcp__tradingview__bollinger_scan with exchange=NASDAQ, timeframe=1D, bbw_threshold=0.08, limit=15 — add any new tickers not already in results
4. For the top 5 results by volume ratio, call mcp__tradingview__combined_analysis (exchange=NASDAQ or NYSE, timeframe=1D) — this gives technicals + sentiment + news in one call
4b. For each CALL signal: call mcp__claude_ai_Interactive_Brokers_IBKR__search_contracts
    with query=ticker, security_type=STK to get contract_id (use underlying_contract_id
    from NASDAQ exchange result). Then call
    mcp__claude_ai_Interactive_Brokers_IBKR__get_price_snapshot with that contract_id,
    exchange=NASDAQ, market_data_names=["underlying_today_option_volume",
    "underlying_avg_option_volume", "implied_vol_underlying",
    "implied_volatility_percentile"]. If market is open and data is non-zero, add
    ibkr_data to the signal JSON:
    {
      "call_volume_today": <callVolume>,
      "put_volume_today": <putVolume>,
      "avg_call_volume": <avgCallVolume>,
      "avg_put_volume": <avgPutVolume>,
      "iv_percentile_52w": <high_52w from implied_volatility_percentile>,
      "annual_iv": <annual_iv from implied_vol_underlying>
    }
    If data is zero or unavailable (outside RTH), omit ibkr_data from that signal.

    For each PUT signal: same but verify put volume > avg put volume.
5. Classify each signal as FLOW_REPEAT_SWEEP_CALL_CHART or FLOW_REPEAT_SWEEP_PUT_RISK_OFF based on direction
6. Run: python3 ingest.py '<json array of signals>'

Signal JSON fields (all required):
- ticker: string (e.g. "NVDA")
- exchange: "NASDAQ" or "NYSE"
- price: number
- change_pct: number
- volume_ratio: number (relative volume vs 10d avg)
- flow_strategy: "BULLISH_TECHNICAL" or "BEARISH_TECHNICAL" — ingest_ibkr.py upgrades to FLOW_REPEAT_SWEEP_CALL_CHART/PUT_RISK_OFF when IBKR confirms real options flow
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
