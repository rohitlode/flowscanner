"""
Called by Claude after the IBKR enrichment prompt.
Updates ibkr_flow and re-scores conviction on signals missing IBKR data.
Usage: python3 ingest_ibkr.py '<json array of {ticker, ibkr_data}>'
"""
from __future__ import annotations
import sys
import json
import db
from conviction import score_conviction
from ibkr_flow import score_ibkr_flow


def enrich_ibkr(items: list[dict]) -> int:
    updated = 0
    with db.get_conn() as conn:
        for item in items:
            ticker = item.get("ticker", "").upper()
            ibkr_data = item.get("ibkr_data")
            if not ticker or not ibkr_data:
                continue

            # get today's active signal for this ticker
            rows = conn.execute(
                "SELECT * FROM signals WHERE ticker=? AND status='active' ORDER BY created_at DESC LIMIT 1",
                (ticker,)
            ).fetchall()
            if not rows:
                continue

            sig = dict(rows[0])
            flow_strategy = sig.get("flow_strategy", "")

            # score IBKR flow
            ibkr_result = score_ibkr_flow(ticker, ibkr_data, flow_strategy)
            if not ibkr_result.get("ibkr_available"):
                continue

            # re-score full conviction with ibkr_data injected
            sig["ibkr_data"] = ibkr_data
            enriched = score_conviction(sig, run_ah_check=False)

            conn.execute("""
                UPDATE signals SET
                  ibkr_flow=?, conviction_tier=?, conviction_label=?, sizing=?
                WHERE id=?
            """, (
                json.dumps(ibkr_result),
                enriched["conviction_tier"],
                enriched["conviction_label"],
                enriched["sizing"],
                sig["id"],
            ))
            updated += 1
            print(f"  {ticker}: {enriched['conviction_label']} | cp_ratio={ibkr_result.get('call_put_ratio','?'):.2f} | flow_confirmed={ibkr_result.get('flow_confirmed')}")

    return updated


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 ingest_ibkr.py '<json>'")
        sys.exit(1)
    data = json.loads(sys.argv[1])
    if isinstance(data, dict):
        data = [data]
    n = enrich_ibkr(data)
    print(f"Enriched {n} signals with IBKR flow data")
