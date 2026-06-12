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
                 "mcp__tradingview__multi_timeframe_analysis,Bash"],
                capture_output=True, text=True,
                timeout=config.CLAUDE_TIMEOUT,
                env={**os.environ, "PYTHONPATH": str(config.FLOWSCANNER_HOME)},
            )
            if result.returncode == 0:
                return "claude scan completed"
            return f"claude rc={result.returncode}: {result.stderr[:200]}"
        except Exception as e:
            return f"claude failed: {e}"
    return _direct_fallback()

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
