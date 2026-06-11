from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path
import secrets, os
import db
import state

app = FastAPI(title="FlowScanner", docs_url=None, redoc_url=None)
security = HTTPBasic()

import logging as _logging
_scan_log_path = Path(__file__).parent / "logs" / "scan.log"
_scan_log_path.parent.mkdir(exist_ok=True)
_scan_logger = _logging.getLogger("scan")
_scan_logger.setLevel(_logging.DEBUG)
_scan_logger.propagate = False
if not _scan_logger.handlers:
    _scan_fh = _logging.FileHandler(_scan_log_path)
    _scan_fh.setFormatter(_logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    _scan_logger.addHandler(_scan_fh)
scan_log = _scan_logger.info
scan_err = _scan_logger.error

AUTH_USER = os.environ.get("DASH_USER", "rohit")
AUTH_PASS = os.environ.get("DASH_PASS", "changeme123")

def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username.encode(), AUTH_USER.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), AUTH_PASS.encode())
    if not (ok_user and ok_pass):
        from fastapi import HTTPException
        from fastapi.responses import Response
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic realm='FlowScanner'"},
        )
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=RedirectResponse)
def root(auth=Depends(require_auth)):
    return "/flow-trades"


@app.get("/flow-trades", response_class=HTMLResponse)
def flow_trades(request: Request):
    signals = db.get_signals()
    scan_runs = db.get_scan_runs()
    return templates.TemplateResponse("flow_trades.html", {
        "request": request,
        "signals": signals,
        "scan_runs": scan_runs,
        "active_tab": "flow_trades",
        "auto_on": state.auto_enabled(),
        "interval": state.get_interval(),
    })


@app.get("/flow-trades/rows", response_class=HTMLResponse)
def flow_trades_rows(request: Request):
    signals = db.get_signals()
    return templates.TemplateResponse("partials/signal_rows.html", {
        "request": request,
        "signals": signals,
    })


@app.get("/scanner", response_class=HTMLResponse)
def scanner(request: Request):
    scan_runs = db.get_scan_runs()
    return templates.TemplateResponse("scanner.html", {
        "request": request,
        "scan_runs": scan_runs,
        "active_tab": "scanner",
    })


@app.get("/open-trades", response_class=HTMLResponse)
def open_trades(request: Request):
    signals = [s for s in db.get_signals() if s.get("entry_price")]
    return templates.TemplateResponse("open_trades.html", {
        "request": request,
        "signals": signals,
        "active_tab": "open_trades",
    })


@app.post("/scan", response_class=HTMLResponse)
def trigger_scan(request: Request):
    import threading, subprocess, os
    def _run():
        scan_log("▶ Scan started")
        try:
            prompt_file = Path(__file__).parent / "prompts" / "scan.md"
            prompt = prompt_file.read_text()
            mcp_config = "/Users/rohitlode/Desktop/claude/config/claude_desktop_config.json"
            scan_log("→ Calling Claude CLI + TradingView MCP…")
            result = subprocess.run(
                ["/usr/local/bin/claude", "-p", prompt,
                 "--mcp-config", mcp_config,
                 "--allowedTools",
                 "mcp__tradingview__smart_volume_scanner,"
                 "mcp__tradingview__volume_breakout_scanner,"
                 "mcp__tradingview__multi_timeframe_analysis,Bash"],
                capture_output=True, text=True, timeout=180,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
            )
            if result.returncode == 0:
                scan_log(f"✓ Claude scan completed")
            else:
                scan_err(f"✗ Claude rc={result.returncode}: {result.stderr[:300]}")
        except Exception as e:
            scan_err(f"✗ Claude error: {e} — falling back to direct scan")
            try:
                from scanner import run_scan
                from ingest import ingest
                from backtester import backtest_and_store
                scan_log("→ Direct TradingView screener (fallback)…")
                sigs, candidates = run_scan()
                scan_log(f"  {len(sigs)} signals from {candidates} candidates")
                for s in sigs: s["_candidates"] = candidates
                ingest(sigs)
                seen = set()
                for s in sigs:
                    if s["ticker"] not in seen:
                        seen.add(s["ticker"])
                        backtest_and_store(s["ticker"])
                scan_log(f"✓ Fallback done — {len(sigs)} signals ingested")
            except Exception as e2:
                scan_err(f"✗ Fallback error: {e2}")
    threading.Thread(target=_run, daemon=True).start()
    return HTMLResponse("""<span style="color:#22c55e;font-size:11px;">
        ⟳ Scanning via Claude + TradingView MCP… results in ~30s
    </span>""")


@app.post("/check-exits", response_class=HTMLResponse)
def check_exits(request: Request):
    state.set_exit_check_requested(True)
    return HTMLResponse("""<span style="color:#f59e0b;font-size:11px;">
        Exit check queued
    </span>""")


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_ticker(request: Request):
    form = await request.form()
    ticker = (form.get("ticker") or "").strip().upper()
    if not ticker:
        return HTMLResponse("<span style='color:#ef4444;font-size:11px;'>Enter a ticker first</span>")

    import threading, time

    result_box = {"html": f"<span style='color:#888;font-size:11px;'>⟳ Analyzing {ticker}…</span>"}

    def _run():
        try:
            import subprocess, os
            prompt_file = Path(__file__).parent / "prompts" / "analyze.md"
            prompt = prompt_file.read_text().replace("{TICKER}", ticker)
            mcp_config = "/Users/rohitlode/Desktop/claude/config/claude_desktop_config.json"
            subprocess.run(
                ["/usr/local/bin/claude", "-p", prompt,
                 "--mcp-config", mcp_config,
                 "--allowedTools",
                 "mcp__tradingview__multi_timeframe_analysis,"
                 "mcp__tradingview__multi_agent_analysis,"
                 "mcp__tradingview__financial_news,Bash"],
                capture_output=True, text=True, timeout=180,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
            )
            # after claude runs, check if signal was ingested
            from db import get_signals
            sigs = get_signals(limit=5)
            today_sig = next((s for s in sigs if s["ticker"] == ticker), None)
            if today_sig:
                result_box["html"] = (
                    f"<span style='color:#22c55e;font-size:11px;'>"
                    f"✓ {ticker} analyzed via Claude MCP — {today_sig.get('conviction_label','')}</span>"
                )
                return

            # fallback to direct analysis if claude didn't ingest
            from scanner import analyze_ticker as do_flow
            from backtester import backtest_and_store
            from ingest import ingest

            # step 1 — flow analysis
            sig = do_flow(ticker)

            # step 2 — backtest
            bt = backtest_and_store(ticker)

            # step 3 — decide
            passes = bt and bt["test_bucket"] in ("VALIDATED_TEST", "WATCH") and bt["win_rate"] >= 0.45

            if passes:
                sig["entry_price"] = sig["price"]   # auto-open the trade
                sig["test_bucket"] = bt["test_bucket"]
                ingest([sig])
                result_box["html"] = (
                    f"<span style='color:#22c55e;font-size:11px;'>"
                    f"✓ {ticker} → {bt['test_bucket']} | "
                    f"wr {bt['win_rate']:.0%} | {sig['flow_strategy'].replace('FLOW_REPEAT_SWEEP_','')} — trade opened</span>"
                )
            else:
                wr  = f"{bt['win_rate']:.0%}" if bt else "n/a"
                bkt = bt["test_bucket"] if bt else "no data"
                ingest([sig])   # still record signal, just don't open trade
                result_box["html"] = (
                    f"<span style='color:#f59e0b;font-size:11px;'>"
                    f"⚠ {ticker} signal recorded but not opened — "
                    f"backtest {bkt} (wr {wr})</span>"
                )
        except ValueError as e:
            result_box["html"] = f"<span style='color:#ef4444;font-size:11px;'>✗ {e}</span>"
        except Exception as e:
            result_box["html"] = f"<span style='color:#ef4444;font-size:11px;'>✗ Error: {e}</span>"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=30)   # wait up to 30s so HTMX gets a real response
    return HTMLResponse(result_box["html"])


@app.post("/auto-toggle", response_class=HTMLResponse)
def auto_toggle(request: Request):
    new_state = state.toggle_auto()
    label = "Auto: On" if new_state else "Auto: Off"
    color = "#22c55e" if new_state else "#888"
    return HTMLResponse(f'<button class="btn btn-secondary" hx-post="/auto-toggle" hx-swap="outerHTML" style="color:{color}">{label}</button>')


@app.post("/set-interval", response_class=HTMLResponse)
async def set_interval(request: Request, auth=Depends(require_auth)):
    form = await request.form()
    val = form.get("interval", "Every 1 min")
    state.set_interval(val)
    return HTMLResponse("")


@app.get("/analytics", response_class=HTMLResponse)
def analytics(request: Request):
    results = db.get_backtest_results()
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "results": results,
        "active_tab": "analytics",
    })


@app.post("/backtest/{ticker}", response_class=HTMLResponse)
def run_backtest(ticker: str):
    import threading
    def _run():
        from backtester import backtest_and_store
        backtest_and_store(ticker.upper())
    threading.Thread(target=_run, daemon=True).start()
    return HTMLResponse(f"<span style='color:#22c55e;font-size:11px;'>⟳ Backtesting {ticker.upper()}…</span>")


@app.get("/logs/tail", response_class=HTMLResponse)
def logs_tail():
    log_file = Path(__file__).parent / "logs" / "scan.log"
    try:
        lines = log_file.read_text().splitlines()[-80:]
    except Exception:
        lines = ["(no scan activity yet — click Scan Now to start)"]

    colored = []
    for line in lines:
        if "✗" in line or "error" in line.lower():
            colored.append(f'<span style="color:#ef4444">{line}</span>')
        elif "✓" in line or "done" in line.lower() or "ingested" in line.lower():
            colored.append(f'<span style="color:#22c55e">{line}</span>')
        elif "▶" in line or "→" in line:
            colored.append(f'<span style="color:#60a5fa">{line}</span>')
        else:
            colored.append(line)

    html = "\n".join(colored)
    return HTMLResponse(f'{html}<script>var el=document.getElementById("log-tail");if(el)el.scrollTop=el.scrollHeight;</script>')


@app.get("/status", response_class=JSONResponse)
def status():
    return {
        "auto": state.auto_enabled(),
        "scan_requested": state.scan_requested(),
        "exit_check_requested": state.exit_check_requested(),
        "signal_count": len(db.get_signals()),
    }


@app.get("/pipeline", response_class=HTMLResponse)
def pipeline(request: Request, auth=Depends(require_auth)):
    stats, runs = db.get_pipeline_stats()
    return templates.TemplateResponse("pipeline.html", {
        "request": request,
        "stats": stats,
        "runs": runs,
        "active_tab": "pipeline",
    })


@app.get("/report", response_class=HTMLResponse)
def report(request: Request, auth=Depends(require_auth)):
    stats = db.get_report_stats()
    return templates.TemplateResponse("report.html", {
        "request": request,
        "stats": stats,
        "active_tab": "report",
    })


def _auto_scan_loop():
    """Background thread: runs scans on the user-selected interval when Auto is On."""
    import time, subprocess, os
    interval_map = {
        "Every 1 min":  60,
        "Every 5 min":  300,
        "Every 15 min": 900,
    }
    while True:
        try:
            if state.auto_enabled():
                interval_str = state.get_interval()
                sleep_secs = interval_map.get(interval_str, 300)
                time.sleep(sleep_secs)
                if state.auto_enabled():  # re-check after sleep
                    scan_log(f"▶ Auto-scan triggered ({interval_str})")
                    try:
                        prompt_file = Path(__file__).parent / "prompts" / "scan.md"
                        prompt = prompt_file.read_text()
                        mcp_config = "/Users/rohitlode/Desktop/claude/config/claude_desktop_config.json"
                        result = subprocess.run(
                            ["/usr/local/bin/claude", "-p", prompt,
                             "--mcp-config", mcp_config,
                             "--allowedTools",
                             "mcp__tradingview__smart_volume_scanner,"
                             "mcp__tradingview__volume_breakout_scanner,"
                             "mcp__tradingview__multi_timeframe_analysis,Bash"],
                            capture_output=True, text=True, timeout=180,
                            env={**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
                        )
                        if result.returncode == 0:
                            scan_log("✓ Auto-scan completed")
                        else:
                            scan_err(f"✗ Auto-scan rc={result.returncode}: {result.stderr[:200]}")
                    except Exception as e:
                        scan_err(f"✗ Auto-scan error: {e}")
            else:
                time.sleep(30)  # idle: check again in 30s
        except Exception:
            time.sleep(60)


import threading as _threading
_threading.Thread(target=_auto_scan_loop, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard:app", host="0.0.0.0", port=8765, reload=True)
