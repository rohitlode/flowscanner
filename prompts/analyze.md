Analyze a single ticker using TradingView MCP tools and push to FlowScanner.

Ticker: {TICKER}

Steps:
1. Call mcp__tradingview__combined_analysis for {TICKER} on NASDAQ, timeframe=1D
   — this returns technicals + Reddit sentiment + news in one call
2. Call mcp__tradingview__multi_timeframe_analysis for {TICKER} on NASDAQ
   — for multi-TF confirmation (weekly → daily → 4H → 1H)
2b. Call mcp__claude_ai_Interactive_Brokers_IBKR__search_contracts for {TICKER}
    (security_type=STK) to get contract_id, then
    mcp__claude_ai_Interactive_Brokers_IBKR__get_price_snapshot with
    market_data_names=["underlying_today_option_volume", "underlying_avg_option_volume",
    "implied_vol_underlying", "implied_volatility_percentile"]. Add ibkr_data to signal
    JSON if data is non-zero:
    {
      "call_volume_today": <callVolume>,
      "put_volume_today": <putVolume>,
      "avg_call_volume": <avgCallVolume>,
      "avg_put_volume": <avgPutVolume>,
      "iv_percentile_52w": <high_52w from implied_volatility_percentile>,
      "annual_iv": <annual_iv from implied_vol_underlying>
    }
    If data is zero or unavailable (outside RTH), omit ibkr_data from signal JSON.
3. Classify signal: FLOW_REPEAT_SWEEP_CALL_CHART or FLOW_REPEAT_SWEEP_PUT_RISK_OFF
4. Run: python3 ingest.py '<json>'

Signal JSON fields:
- ticker, exchange, price, change_pct, volume_ratio
- flow_strategy: "BULLISH_TECHNICAL" or "BEARISH_TECHNICAL" — ingest_ibkr.py upgrades to FLOW_REPEAT_SWEEP_CALL_CHART/PUT_RISK_OFF when IBKR confirms real options flow
- test_bucket: "WATCH" or "UNVALIDATED" only — never emit "VALIDATED_TEST"
- direction: "long" or "short"
- confidence: 40-95
- analysis_summary: key metrics — price, RSI, MACD crossover, support/resistance levels, trend state, confluence verdict
- sentiment: "bullish", "bearish", or "neutral" (from combined_analysis confluence)
- rsi_signal: "oversold", "overbought", or "neutral"
- macd_signal_dir: "bullish" or "bearish"
- price_vs_ema: "above" or "below" (vs EMA200)

Keep it focused — analyze, classify, ingest. No explanations needed.
