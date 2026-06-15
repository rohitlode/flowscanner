from __future__ import annotations
import subprocess, os
from pathlib import Path
import config, guards, db

def run_scan_once(trigger: str = "manual") -> str:
    try:
        with guards.ScanLock():
            return _do_scan(trigger)
    except guards.ScanLock.Busy as e:
        return f"skipped — {e}"
    except Exception as e:
        return f"error — {e}"

def _do_scan(trigger: str) -> str:
    use_claude = (
        config.claude_available()
        and Path(config.MCP_CONFIG).exists()
        and db.can_spend_credit()
    )
    if use_claude:
        db.record_credit("scan", trigger)
        try:
            prompt = (config.PROMPTS_DIR / "scan.md").read_text()
            result = subprocess.run(
                [config.CLAUDE_BIN, "-p", prompt,
                 "--mcp-config", config.MCP_CONFIG,
                 "--allowedTools",
                 "mcp__tradingview__smart_volume_scanner,"
                 "mcp__tradingview__volume_breakout_scanner,"
                 "mcp__tradingview__bollinger_scan,"
                 "mcp__tradingview__combined_analysis,"
                 "mcp__tradingview__multi_timeframe_analysis,"
                 "mcp__claude_ai_Interactive_Brokers_IBKR__search_contracts,"
                 "mcp__claude_ai_Interactive_Brokers_IBKR__get_price_snapshot,"
                 "Bash"],
                capture_output=True, text=True,
                timeout=config.CLAUDE_TIMEOUT,
                env={**os.environ, "PYTHONPATH": str(config.FLOWSCANNER_HOME)},
            )
            if result.returncode == 0:
                enrich_uw_signals()
                enrich_ibkr_signals()
                return "claude scan completed"
            return f"claude rc={result.returncode}: {result.stderr[:200]}"
        except Exception as e:
            return f"claude failed: {e}"
    status = _direct_fallback()
    enrich_uw_signals()
    enrich_ibkr_signals()
    return status

def enrich_uw_signals() -> str:
    """
    Enrich today's signals with Unusual Whales real sweep/flow data.
    Pure Python HTTP — no Claude CLI, no MCP, no credits.
    """
    try:
        from ingest_uw import enrich_uw_signals as _enrich
        n = _enrich()
        return f"UW enrichment: {n} signals updated"
    except Exception as e:
        return f"UW enrichment error: {e}"


def enrich_ibkr_signals() -> str:
    """
    After any scan, enrich signals missing ibkr_flow with real IBKR options data.
    Runs as a separate Claude call with only IBKR tools allowed — fast, focused.
    Returns status string. Never raises.
    """
    try:
        if not config.claude_available() or not Path(config.MCP_CONFIG).exists():
            return "skipped — Claude/MCP not available"
        if not db.can_spend_credit():
            return "skipped — daily credit cap reached"

        # find today's signals missing ibkr_flow
        with db.get_conn() as conn:
            rows = conn.execute("""
                SELECT DISTINCT ticker FROM signals
                WHERE status='active'
                AND (ibkr_flow IS NULL OR ibkr_flow = '')
                AND DATE(created_at) = DATE('now')
            """).fetchall()

        tickers = [r["ticker"] for r in rows]
        if not tickers:
            return "no signals need IBKR enrichment"

        # batch into groups of 8 — 2 IBKR calls per ticker × 8 = 16 calls per batch
        BATCH = 8
        batches = [tickers[i:i+BATCH] for i in range(0, len(tickers), BATCH)]
        enriched = 0
        prompt_template = (config.PROMPTS_DIR / "enrich_ibkr.md").read_text()

        for batch in batches:
            if not db.can_spend_credit():
                break
            db.record_credit("enrich_ibkr", ",".join(batch))
            prompt = prompt_template.replace("{TICKERS}", ", ".join(batch))
            result = subprocess.run(
                [config.CLAUDE_BIN, "-p", prompt,
                 "--mcp-config", config.MCP_CONFIG,
                 "--allowedTools",
                 "mcp__claude_ai_Interactive_Brokers_IBKR__search_contracts,"
                 "mcp__claude_ai_Interactive_Brokers_IBKR__get_price_snapshot,"
                 "Bash"],
                capture_output=True, text=True,
                timeout=120,
                env={**os.environ, "PYTHONPATH": str(config.FLOWSCANNER_HOME)},
            )
            if result.returncode == 0:
                enriched += len(batch)

        if enriched:
            return f"IBKR enrichment done for {enriched}/{len(tickers)} tickers"
        return f"IBKR enrichment failed — rc={result.returncode}: {result.stderr[:150]}"
    except Exception as e:
        return f"IBKR enrichment error: {e}"


def _direct_fallback() -> str:
    from scanner import run_scan
    from ingest import ingest
    from backtester import backtest_and_store
    sigs, candidates = run_scan()
    for s in sigs:
        s["_candidates"] = candidates
    ingest(sigs)
    seen: set[str] = set()
    for s in sigs:
        t = s["ticker"]
        if t not in seen:
            seen.add(t)
            try:
                backtest_and_store(t)
            except Exception:
                pass
    return f"direct scan: {len(sigs)} signals from {candidates} candidates"
