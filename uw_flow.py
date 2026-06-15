"""
Unusual Whales flow alert scorer.

fetch_and_score(ticker, flow_strategy) → dict
  Calls UW /api/stock/{ticker}/flow-alerts directly (no Claude/MCP needed).
  Returns scored conviction enrichment using real sweep/institutional data.

UW replaces the IBKR call/put proxy when available — it's the actual source
the FlowScanner was designed around.
"""
from __future__ import annotations

import httpx
import config

# Alert rules that indicate confirmed sweeps/institutional prints
_SWEEP_RULES = {
    "RepeatedHitsAscendingFill",
    "RepeatedHitsDescendingFill",
    "SingleLegSweep",
    "MultiLegSweep",
    "SweepAlert",
}

_FLOOR_RULES = {
    "FloorTrade",
    "BlockTrade",
}


def fetch_uw_alerts(ticker: str, limit: int = 10) -> list[dict]:
    """Fetch recent flow alerts for a ticker from Unusual Whales. Returns [] on failure."""
    try:
        url = f"{config.UW_BASE_URL}/api/stock/{ticker}/flow-alerts"
        r = httpx.get(
            url,
            headers={"Authorization": f"Bearer {config.UW_API_KEY}"},
            params={"limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def score_uw_flow(ticker: str, flow_strategy: str, alerts: list[dict] | None = None) -> dict:
    """
    Score UW flow alerts for a ticker against its signal direction.

    Parameters
    ----------
    ticker : str
    flow_strategy : str   FLOW_REPEAT_SWEEP_CALL_CHART | FLOW_REPEAT_SWEEP_PUT_RISK_OFF | BULLISH_TECHNICAL | BEARISH_TECHNICAL
    alerts : list[dict]   Pre-fetched alerts (pass None to fetch live)

    Returns
    -------
    dict with keys:
        uw_available     bool
        flow_confirmed   bool
        flow_direction   None | "FLIP" | "SKIP"
        flow_score       int  (0–6, added to conviction score)
        flow_notes       list[str]
        sweep_count      int
        floor_count      int
        total_premium    float
        largest_alert    dict | None
        iv_crush_risk    bool
    """
    if alerts is None:
        alerts = fetch_uw_alerts(ticker)

    if not alerts:
        return {"uw_available": False}

    is_bullish = "CALL" in flow_strategy or "BULLISH" in flow_strategy
    is_bearish = "PUT" in flow_strategy or "BEARISH" in flow_strategy

    # Filter to direction-aligned alerts (last 24h)
    call_alerts = [a for a in alerts if a.get("type") == "call"]
    put_alerts  = [a for a in alerts if a.get("type") == "put"]

    aligned   = call_alerts if is_bullish else put_alerts
    opposing  = put_alerts  if is_bullish else call_alerts

    aligned_premium  = sum(float(a.get("total_premium", 0)) for a in aligned)
    opposing_premium = sum(float(a.get("total_premium", 0)) for a in opposing)
    total_premium    = aligned_premium + opposing_premium

    sweep_count = sum(1 for a in aligned if a.get("has_sweep") or a.get("alert_rule") in _SWEEP_RULES)
    floor_count = sum(1 for a in aligned if a.get("has_floor") or a.get("alert_rule") in _FLOOR_RULES)
    opening_count = sum(1 for a in aligned if a.get("all_opening_trades"))

    # Largest single aligned alert
    largest = max(aligned, key=lambda a: float(a.get("total_premium", 0)), default=None)

    # IV crush risk — IV > 80th percentile proxy: iv_end > 0.6
    iv_crush_risk = any(float(a.get("iv_end") or 0) > 0.6 for a in aligned)

    # ── Scoring ────────────────────────────────────────────────────────────
    score = 0
    notes: list[str] = []
    flow_confirmed = True
    flow_direction: str | None = None

    # Direction alignment check
    if opposing_premium > aligned_premium * 2:
        flow_confirmed = False
        flow_direction = "FLIP"
        side = "PUT" if is_bullish else "CALL"
        notes.append(f"🔴 FLIP — {side} premium dominates (${opposing_premium/1e3:.0f}k vs ${aligned_premium/1e3:.0f}k) — consider opposite direction")
    elif opposing_premium > aligned_premium:
        flow_confirmed = False
        flow_direction = "SKIP"
        notes.append(f"⚠ SKIP — opposing flow exceeds aligned (${opposing_premium/1e3:.0f}k vs ${aligned_premium/1e3:.0f}k)")

    if flow_confirmed:
        # Sweep confirmation
        if sweep_count >= 2:
            score += 3
            notes.append(f"🔥 {sweep_count} confirmed sweeps — institutional accumulation")
        elif sweep_count == 1:
            score += 2
            notes.append("Sweep detected — institutional directional bet")

        # Floor/block trades
        if floor_count >= 1:
            score += 1
            notes.append(f"Floor/block trade detected ({floor_count})")

        # Premium size
        if aligned_premium >= config.UW_LARGE_PREMIUM_THRESHOLD:
            score += 2
            notes.append(f"Very large premium ${aligned_premium/1e6:.1f}M — conviction size")
        elif aligned_premium >= config.UW_SWEEP_PREMIUM_THRESHOLD:
            score += 1
            notes.append(f"Institutional premium ${aligned_premium/1e3:.0f}k")

        # Opening trades (new positions, not closing)
        if opening_count >= 1:
            score += 1
            notes.append(f"{opening_count} opening trade(s) — new position, not closing")

        # Volume/OI ratio
        high_vol_oi = [a for a in aligned if float(a.get("volume_oi_ratio", 0)) > config.UW_HIGH_VOL_OI_RATIO]
        if high_vol_oi:
            score += 1
            notes.append(f"Vol/OI ratio {float(high_vol_oi[0]['volume_oi_ratio']):.1f}x — unusual relative to open interest")

    if iv_crush_risk:
        notes.append("⚠ IV elevated (>60%) — expensive premium, IV crush risk")

    return {
        "uw_available":   True,
        "flow_confirmed": flow_confirmed,
        "flow_direction": flow_direction,
        "flow_score":     score,
        "flow_notes":     notes,
        "sweep_count":    sweep_count,
        "floor_count":    floor_count,
        "total_premium":  round(total_premium, 2),
        "aligned_premium": round(aligned_premium, 2),
        "opposing_premium": round(opposing_premium, 2),
        "largest_alert":  largest,
        "iv_crush_risk":  iv_crush_risk,
        "alert_count":    len(alerts),
    }
