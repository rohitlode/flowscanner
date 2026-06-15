"""
Conviction tier engine.

Assigns 🔥 HIGH / ⚡ MODERATE / 📊 NO FLOW to every signal.
Inputs are all available without options flow — upgrades automatically
when Unusual Whales is wired in (flow_strategy becomes real sweep data).

Tier definitions (proxy mode, no UW):
  🔥 HIGH       vol_ratio > 2.5 + VALIDATED_TEST + not micro-cap + no AH fade
  ⚡ MODERATE   vol_ratio 1.5-2.5 OR WATCH bucket OR any single strong signal
  📊 NO FLOW    vol_ratio < 1.5 OR micro-cap thin options OR AH fade detected

When UW is wired in:
  🔥 HIGH       real sweep confirmed + call/put ratio >2 + OTM cluster
  ⚡ MODERATE   elevated flow but not sweep-level
  📊 NO FLOW    normal options volume
"""

import yfinance as yf


# ── Key flow patterns (for analysis_summary note) ──────────────────────────
FLOW_PATTERNS = {
    "strike_laddering":    "Strike Laddering — smart money scaling in",
    "high_cp_ratio":       "5:1+ Call/Put — one-directional institutional",
    "otm_cluster":         "OTM Strike Cluster — big move expected",
    "protective_puts":     "Protective Puts + Long — institutions holding",
    "post_deal_surge":     "Post-Deal Call Surge — re-rating not priced in",
    "pre_earnings_skew":   "Pre-Earnings Premium Skew — institutions paying up",
}


def _get_market_cap(ticker: str) -> float:
    """Returns market cap in USD. Returns 0 on failure."""
    try:
        info = yf.Ticker(ticker).info
        return float(info.get("marketCap") or 0)
    except Exception:
        return 0


def _check_ah_fade(ticker: str) -> bool:
    """
    Returns True if AH fade detected:
    after-hours price gave back >50% of day's gain vs previous close.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info
        regular_close = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0)
        prev_close    = float(info.get("regularMarketPreviousClose") or 0)
        post_price    = float(info.get("postMarketPrice") or regular_close)

        if prev_close <= 0 or regular_close <= prev_close:
            return False

        day_gain   = regular_close - prev_close
        ah_retrace = regular_close - post_price
        return ah_retrace > (day_gain * 0.5)
    except Exception:
        return False


def score_conviction(signal: dict, run_ah_check: bool = True) -> dict:
    """
    Takes a signal dict, returns it enriched with:
      - conviction_tier: "HIGH" | "MODERATE" | "NO_FLOW"
      - conviction_label: emoji + label string
      - sizing: "FULL SIZE" | "HALF SIZE" | "QUARTER SIZE"
      - conviction_reasons: list of strings explaining the tier
      - ah_fade_skip: True if AH fade detected (skip next-day entry)
      - flow_patterns: list of detected pattern keys
    """
    ticker     = signal.get("ticker", "")
    vol_ratio  = signal.get("volume_ratio") or 0
    test_bucket = signal.get("test_bucket", "UNVALIDATED")
    rsi        = signal.get("rsi") or 50
    chg_pct    = signal.get("change_pct") or 0
    macd_dir   = signal.get("macd_signal_dir", "bearish")
    flow_strat = signal.get("flow_strategy", "")
    # normalise — BULLISH_TECHNICAL treated as CALL, BEARISH_TECHNICAL as PUT
    _is_bullish = "CALL" in flow_strat or flow_strat == "BULLISH_TECHNICAL"
    _is_bearish = "PUT"  in flow_strat or flow_strat == "BEARISH_TECHNICAL"

    # ── AH Fade check ─────────────────────────────────────────────────────
    ah_fade = False
    if run_ah_check:
        try:
            ah_fade = _check_ah_fade(ticker)
        except Exception:
            pass

    # ── Market cap check (micro-cap = unreliable options) ─────────────────
    market_cap   = _get_market_cap(ticker)
    is_micro_cap = 0 < market_cap < 1_000_000_000  # < $1B

    # ── Flow pattern detection (proxy — from price/volume signals) ─────────
    patterns = []
    if vol_ratio > 5:
        patterns.append("strike_laddering")   # extreme volume = scaling in
    if abs(chg_pct) > 8 and vol_ratio > 2:
        patterns.append("otm_cluster")        # big move + volume = OTM target
    if _is_bearish and vol_ratio > 2:
        patterns.append("protective_puts")

    # ── Conviction scoring ─────────────────────────────────────────────────
    reasons = []
    score   = 0

    # Volume signals
    if vol_ratio > 2.5:
        score += 2
        reasons.append(f"Vol {vol_ratio:.1f}x avg (calls >150% threshold)")
    elif vol_ratio > 1.5:
        score += 1
        reasons.append(f"Vol {vol_ratio:.1f}x avg (elevated)")

    # Backtest quality
    if test_bucket == "VALIDATED_TEST":
        score += 2
        reasons.append("Backtest VALIDATED_TEST (≥55% win rate, ≥8 trades)")
    elif test_bucket == "WATCH":
        score += 1
        reasons.append("Backtest WATCH (≥45% win rate)")

    # Technical alignment
    if macd_dir == "bullish" and rsi > 50:
        score += 1
        reasons.append("MACD bullish + RSI > 50")
    elif macd_dir == "bearish" and rsi < 50 and _is_bearish:
        score += 1
        reasons.append("MACD bearish + RSI < 50 (PUT setup confirmed)")

    # Price move strength
    if abs(chg_pct) >= 4:
        score += 1
        reasons.append(f"Strong move {chg_pct:+.1f}%")

    # Micro-cap penalty
    if is_micro_cap:
        score = min(score, 1)
        reasons.append(f"⚠ Micro-cap (${market_cap/1e6:.0f}M) — options flow unreliable, using fundamentals")

    # AH fade override
    if ah_fade:
        score = 0
        reasons = ["⚠ AH FADE DETECTED — institutions distributing into strength — SKIP"]

    # ── Unusual Whales flow enrichment (real sweep data — highest priority) ──
    uw_result: dict = {}
    uw_data = signal.get("uw_data")  # pre-fetched alerts list
    if uw_data is not None or signal.get("_fetch_uw", False):
        from uw_flow import score_uw_flow
        uw_result = score_uw_flow(ticker, signal.get("flow_strategy", ""), alerts=uw_data)

    if uw_result.get("uw_available"):
        score += uw_result.get("flow_score", 0)
        reasons.extend(uw_result.get("flow_notes", []))
        flow_dir = uw_result.get("flow_direction")
        if flow_dir == "FLIP":
            score = 0
            reasons = uw_result.get("flow_notes", [])
        elif flow_dir == "SKIP":
            score = 0
            reasons = uw_result.get("flow_notes", [])
        if uw_result.get("iv_crush_risk"):
            reasons.append("⚠ IV crush risk — elevated IV on alert")
    else:
        # ── IBKR call/put volume (fallback when UW unavailable) ──────────
        ibkr_data = signal.get("ibkr_data")
        if ibkr_data:
            from ibkr_flow import score_ibkr_flow
            ibkr_result: dict = score_ibkr_flow(
                ticker, ibkr_data, signal.get("flow_strategy", "")
            )
            if ibkr_result.get("ibkr_available"):
                score += ibkr_result.get("flow_score", 0)
                reasons.extend(ibkr_result.get("flow_notes", []))
                flow_dir = ibkr_result.get("flow_direction")
                if flow_dir in ("FLIP", "SKIP"):
                    score = 0
                    reasons = ibkr_result.get("flow_notes", [])
                if ibkr_result.get("iv_crush_risk"):
                    reasons.append("⚠ IV crush risk — expensive premium")
        else:
            ibkr_result = {}

    # ── Assign tier ────────────────────────────────────────────────────────
    uw_flip  = uw_result.get("uw_available") and uw_result.get("flow_direction") == "FLIP"
    uw_skip  = uw_result.get("uw_available") and uw_result.get("flow_direction") == "SKIP"
    ibkr_result = signal.get("_ibkr_result", {}) if not uw_result.get("uw_available") else {}
    ibkr_flip = not uw_result.get("uw_available") and ibkr_result.get("flow_direction") == "FLIP" and ibkr_result.get("ibkr_available")
    ibkr_skip = not uw_result.get("uw_available") and ibkr_result.get("flow_direction") == "SKIP" and ibkr_result.get("ibkr_available")

    if uw_flip or ibkr_flip:
        tier, label, sizing = "SKIP", "🔴 FLOW FLIP — DO NOT ENTER", "DO NOT ENTER"
    elif uw_skip or ibkr_skip:
        tier, label, sizing = "SKIP", "⛔ NO FLOW CONVICTION — SKIP", "DO NOT ENTER"
    elif ah_fade:
        tier, label, sizing = "SKIP", "⚠ AH FADE — SKIP", "DO NOT ENTER"
    elif score >= 4:
        tier, label, sizing = "HIGH",     "🔥 HIGH CONVICTION",      "FULL SIZE"
    elif score >= 2:
        tier, label, sizing = "MODERATE", "⚡ MODERATE CONVICTION",   "HALF SIZE"
    else:
        tier, label, sizing = "NO_FLOW",  "📊 NO FLOW CONFIRMATION",  "QUARTER SIZE"

    # ── Flow source suffix ─────────────────────────────────────────────────
    if uw_result.get("uw_available"):
        flow_suffix = " (UW sweep confirmed)" if uw_result.get("sweep_count", 0) > 0 else " (UW flow confirmed)"
    elif signal.get("ibkr_data") and any(
        v.get("ibkr_available") for v in [signal.get("_ibkr_result", {})]
    ):
        flow_suffix = " (IBKR volume confirmed)"
    else:
        flow_suffix = " (proxy)"

    return {
        **signal,
        "conviction_tier":    tier,
        "conviction_label":   label + flow_suffix,
        "sizing":             sizing,
        "conviction_reasons": reasons,
        "ah_fade_skip":       ah_fade,
        "flow_patterns":      [FLOW_PATTERNS[p] for p in patterns if p in FLOW_PATTERNS],
        "market_cap_m":       round(market_cap / 1e6, 1) if market_cap else None,
        "is_micro_cap":       is_micro_cap,
        "uw_flow":            uw_result if uw_result.get("uw_available") else None,
        "ibkr_flow":          signal.get("ibkr_flow"),
    }


if __name__ == "__main__":
    # quick test
    test_sig = {
        "ticker": "NVDA", "vol_ratio": 3.2, "test_bucket": "WATCH",
        "rsi": 58, "change_pct": 4.5, "macd_signal_dir": "bullish",
        "flow_strategy": "FLOW_REPEAT_SWEEP_CALL_CHART",
    }
    result = score_conviction(test_sig, run_ah_check=False)
    print(f"\n{result['conviction_label']}")
    print(f"Sizing: {result['sizing']}")
    print(f"Reasons:")
    for r in result['conviction_reasons']:
        print(f"  • {r}")
    if result['flow_patterns']:
        print(f"Patterns: {', '.join(result['flow_patterns'])}")
