"""
Enrich today's signals with Unusual Whales flow data.
Called directly from runner.py — no Claude CLI, no MCP, pure HTTP.
Usage: python3 ingest_uw.py  (or called via enrich_uw_signals())
"""
from __future__ import annotations

import json
import sys
import db
from conviction import score_conviction
from uw_flow import fetch_uw_alerts, score_uw_flow


def enrich_uw_signals() -> int:
    """
    Fetch UW flow alerts for every today's active signal and re-score conviction.
    Returns count of signals updated.
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()

    with db.get_conn() as conn:
        # Use the most recent scan day (not necessarily today — catches weekend scans)
        latest = conn.execute(
            "SELECT DATE(MAX(created_at)) as day FROM signals WHERE status='active'"
        ).fetchone()
        scan_day = latest["day"] if latest and latest["day"] else today
        rows = conn.execute("""
            SELECT * FROM signals
            WHERE status='active'
            AND DATE(created_at) = ?
        """, (scan_day,)).fetchall()

    updated = 0
    for row in rows:
        sig = dict(row)
        ticker = sig.get("ticker", "")
        flow_strategy = sig.get("flow_strategy", "")

        # fetch live UW alerts
        alerts = fetch_uw_alerts(ticker, limit=10)
        if not alerts:
            continue

        uw_result = score_uw_flow(ticker, flow_strategy, alerts=alerts)
        if not uw_result.get("uw_available"):
            continue

        # re-score full conviction with UW data injected
        sig["uw_data"] = alerts
        enriched = score_conviction(sig, run_ah_check=False)

        # upgrade flow_strategy if UW confirms real sweep in right direction
        flow_dir = uw_result.get("flow_direction")
        sweep_count = uw_result.get("sweep_count", 0)
        direction = sig.get("direction", "long")

        if flow_dir == "FLIP":
            upgraded = "FLOW_REPEAT_SWEEP_PUT_RISK_OFF" if direction == "long" else "FLOW_REPEAT_SWEEP_CALL_CHART"
        elif uw_result.get("flow_confirmed") and sweep_count >= 1 and direction == "long":
            upgraded = "FLOW_REPEAT_SWEEP_CALL_CHART"
        elif uw_result.get("flow_confirmed") and sweep_count >= 1 and direction == "short":
            upgraded = "FLOW_REPEAT_SWEEP_PUT_RISK_OFF"
        else:
            upgraded = flow_strategy  # keep existing

        new_direction = "short" if "PUT" in upgraded else "long"

        with db.get_conn() as conn:
            conn.execute("""
                UPDATE signals SET
                  uw_flow=?, flow_strategy=?, direction=?,
                  conviction_tier=?, conviction_label=?, sizing=?
                WHERE id=?
            """, (
                json.dumps(uw_result),
                upgraded,
                new_direction,
                enriched["conviction_tier"],
                enriched["conviction_label"],
                enriched["sizing"],
                sig["id"],
            ))
        updated += 1

        sweep_str = f"{sweep_count} sweep(s)" if sweep_count else "no sweep"
        print(f"  {ticker}: {flow_strategy} → {upgraded} | {enriched['conviction_label']} | {sweep_str} | premium ${uw_result.get('aligned_premium', 0)/1e3:.0f}k")

    return updated


if __name__ == "__main__":
    n = enrich_uw_signals()
    print(f"UW enrichment: {n} signals updated")
