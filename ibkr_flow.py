"""
IBKR options flow scorer.

score_ibkr_flow(ticker, ibkr_data, flow_strategy) interprets real call/put
volume data that Claude extracts from IBKR MCP calls and attaches to signal JSON.
This module is pure Python — it never calls IBKR directly.

Claude calls IBKR MCP → gets JSON → passes as ibkr_data in signal → ingest.py
passes to conviction.py → conviction.py calls score_ibkr_flow here.
"""
from __future__ import annotations


def score_ibkr_flow(
    ticker: str,
    ibkr_data: dict,
    flow_strategy: str,
) -> dict:
    """
    Score IBKR real options flow data for a signal.

    Parameters
    ----------
    ticker : str
        Ticker symbol (for notes).
    ibkr_data : dict
        Keys: call_volume_today, put_volume_today, avg_call_volume,
              avg_put_volume, iv_percentile_52w, annual_iv
    flow_strategy : str
        "FLOW_REPEAT_SWEEP_CALL_CHART" or "FLOW_REPEAT_SWEEP_PUT_RISK_OFF"

    Returns
    -------
    dict
        ibkr_available, call_put_ratio, call_volume_vs_avg, iv_percentile,
        flow_confirmed, flow_score, flow_notes, iv_crush_risk
        — or {"ibkr_available": False} if data is missing / outside RTH.
    """
    # Guard: missing or zero data (outside RTH or no data available)
    call_vol = ibkr_data.get("call_volume_today", 0) or 0
    put_vol  = ibkr_data.get("put_volume_today",  0) or 0
    if call_vol == 0:
        return {"ibkr_available": False}

    avg_call = ibkr_data.get("avg_call_volume", 0) or 0
    avg_put  = ibkr_data.get("avg_put_volume",  0) or 0
    iv_pct   = float(ibkr_data.get("iv_percentile_52w", 0) or 0)

    is_call_signal = "CALL" in flow_strategy
    is_put_signal  = "PUT"  in flow_strategy

    score: int       = 0
    notes: list[str] = []
    flow_confirmed   = True
    iv_crush_risk    = False

    # ── Call/put ratio ──────────────────────────────────────────────────────
    cp_ratio = call_vol / put_vol if put_vol > 0 else float("inf")
    pc_ratio = put_vol  / call_vol if call_vol > 0 else float("inf")

    if is_call_signal:
        if cp_ratio > 2.0:
            score += 2
            notes.append("Strong call dominance (2:1+)")
        elif cp_ratio > 1.5:
            score += 1
            notes.append("Call-leaning flow (1.5:1+)")
        elif cp_ratio < 1.0:
            flow_confirmed = False
            notes.append("⚠ Put-heavy flow contradicts CALL signal")

    elif is_put_signal:
        if pc_ratio > 2.0:
            score += 2
            notes.append("Strong put dominance (2:1+)")
        elif pc_ratio > 1.5:
            score += 1
            notes.append("Put-leaning flow (1.5:1+)")
        elif pc_ratio < 1.0:
            flow_confirmed = False
            notes.append("⚠ Call-heavy flow contradicts PUT signal")

    # ── Volume vs average ───────────────────────────────────────────────────
    if is_call_signal and avg_call > 0:
        vol_vs_avg = call_vol / avg_call
        if vol_vs_avg > 2.0:
            score += 2
            notes.append("Call volume 2x+ above average — institutional sweep likely")
        elif vol_vs_avg > 1.5:
            score += 1
            notes.append("Call volume 1.5x above average — unusual activity")
    elif is_put_signal and avg_put > 0:
        vol_vs_avg = put_vol / avg_put
        if vol_vs_avg > 2.0:
            score += 2
            notes.append("Put volume 2x+ above average — institutional sweep likely")
        elif vol_vs_avg > 1.5:
            score += 1
            notes.append("Put volume 1.5x above average — unusual activity")
    else:
        vol_vs_avg = 0.0

    # ── IV rank ─────────────────────────────────────────────────────────────
    if iv_pct > 0.8:
        iv_crush_risk = True
        notes.append("⚠ IV rank 80%+ — expensive premium, crush risk")
    elif iv_pct < 0.3:
        score += 1
        notes.append("Low IV rank — cheap premium entry")

    # ── Build ratio fields for return ───────────────────────────────────────
    return {
        "ibkr_available":      True,
        "call_put_ratio":      round(cp_ratio if cp_ratio != float("inf") else 0, 2),
        "call_volume_vs_avg":  round(vol_vs_avg, 2),
        "iv_percentile":       iv_pct,
        "flow_confirmed":      flow_confirmed,
        "flow_score":          score,
        "flow_notes":          notes,
        "iv_crush_risk":       iv_crush_risk,
    }
