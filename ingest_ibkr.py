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

            # upgrade flow_strategy from technical → confirmed sweep when IBKR backs it
            flow_dir = ibkr_result.get("flow_direction")  # None | "FLIP" | "SKIP"
            confirmed = ibkr_result.get("flow_confirmed", False)
            cp_ratio = ibkr_result.get("call_put_ratio", 1.0)

            direction = sig.get("direction", "long")

            if flow_dir == "FLIP":
                # IBKR strongly contradicts — flip to the opposite confirmed strategy
                upgraded_strategy = "FLOW_REPEAT_SWEEP_PUT_RISK_OFF" if direction == "long" else "FLOW_REPEAT_SWEEP_CALL_CHART"
            elif flow_dir == "SKIP":
                upgraded_strategy = flow_strategy  # keep as-is, conviction will mark SKIP
            elif confirmed and cp_ratio >= 1.5 and direction == "long":
                upgraded_strategy = "FLOW_REPEAT_SWEEP_CALL_CHART"
            elif confirmed and cp_ratio <= 0.67 and direction == "short":
                upgraded_strategy = "FLOW_REPEAT_SWEEP_PUT_RISK_OFF"
            else:
                upgraded_strategy = flow_strategy  # keep honest technical label

            sig["ibkr_data"] = ibkr_data
            sig["flow_strategy"] = upgraded_strategy
            enriched = score_conviction(sig, run_ah_check=False)

            conn.execute("""
                UPDATE signals SET
                  ibkr_flow=?, flow_strategy=?, direction=?,
                  conviction_tier=?, conviction_label=?, sizing=?
                WHERE id=?
            """, (
                json.dumps(ibkr_result),
                upgraded_strategy,
                "long" if "CALL" in upgraded_strategy or upgraded_strategy == "BULLISH_TECHNICAL" else "short",
                enriched["conviction_tier"],
                enriched["conviction_label"],
                enriched["sizing"],
                sig["id"],
            ))
            updated += 1
            print(f"  {ticker}: {flow_strategy} → {upgraded_strategy} | {enriched['conviction_label']} | cp={cp_ratio:.2f}")

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
