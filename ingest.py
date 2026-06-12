"""
Ingest script — called by Claude Code after running MCP scans.
Usage: python ingest.py '<json>'
The JSON is a list of signal dicts produced by the scan.
"""
import sys
import json
import db


def ingest(signals: list[dict], exchange: str = ""):
    from conviction import score_conviction
    from backtester import backtest_and_store

    # derive exchange label from actual signals if not specified
    if not exchange and signals:
        exchanges = set(s.get("exchange", "") for s in signals if s.get("exchange"))
        exchange = "+".join(sorted(exchanges)) if exchanges else "MIXED"

    db.log_scan_run(
        exchange=exchange or "MIXED",
        candidates=signals[0].get("_candidates", len(signals)) if signals else 0,
        signals_found=len(signals),
    )
    inserted = []
    seen_tickers = set()
    for s in signals:
        s.pop("_candidates", None)

        # score conviction if not already scored
        if not s.get("conviction_tier"):
            s = score_conviction(s, run_ah_check=False)

        sig_id = db.upsert_signal(s)
        inserted.append(sig_id)

        # backtest each ticker once per ingest run (sets test_bucket properly)
        ticker = s.get("ticker")
        if ticker and ticker not in seen_tickers:
            seen_tickers.add(ticker)
            try:
                backtest_and_store(ticker)
            except Exception as e:
                print(f"Backtest skipped for {ticker}: {e}")

    return inserted


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest.py '<json array>'")
        sys.exit(1)
    data = json.loads(sys.argv[1])
    if isinstance(data, dict):
        data = [data]
    ids = ingest(data)
    print(f"Ingested {len(ids)} signals: {ids}")
