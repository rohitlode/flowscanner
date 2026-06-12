Enrich FlowScanner signals with real IBKR options flow data.

Tickers to enrich: {TICKERS}

For each ticker:
1. Call mcp__claude_ai_Interactive_Brokers_IBKR__search_contracts with query=<ticker>, security_type=STK — use the NASDAQ result's underlying_contract_id
2. Call mcp__claude_ai_Interactive_Brokers_IBKR__get_price_snapshot with that contract_id, exchange=NASDAQ, market_data_names=["underlying_today_option_volume","underlying_avg_option_volume","implied_vol_underlying","implied_volatility_percentile"]
3. If callVolume or putVolume is 0 (outside market hours or no data) — skip that ticker
4. Run: python3 ingest_ibkr.py '<json>'

JSON format — array of objects:
[
  {
    "ticker": "NVDA",
    "ibkr_data": {
      "call_volume_today": <callVolume>,
      "put_volume_today": <putVolume>,
      "avg_call_volume": <avgCallVolume>,
      "avg_put_volume": <avgPutVolume>,
      "iv_percentile_52w": <high_52w from implied_volatility_percentile>,
      "annual_iv": <annual_iv from implied_vol_underlying>
    }
  }
]

Only include tickers where data is non-zero. Skip tickers with no options (callVolume=0).
Keep it fast — no analysis, just pull and ingest.
