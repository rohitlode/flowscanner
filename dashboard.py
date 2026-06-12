from __future__ import annotations
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path
import secrets, os
import db
import state
import config
import guards
import runner
from logging.handlers import RotatingFileHandler

app = FastAPI(title="FlowScanner", docs_url=None, redoc_url=None)
security = HTTPBasic()

import logging as _logging
_scan_log_path = config.LOGS_DIR / "scan.log"
_scan_logger = _logging.getLogger("scan")
_scan_logger.setLevel(_logging.DEBUG)
_scan_logger.propagate = False
if not _scan_logger.handlers:
    _scan_fh = RotatingFileHandler(_scan_log_path, maxBytes=5*1024*1024, backupCount=3)
    _scan_fh.setFormatter(_logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    _scan_logger.addHandler(_scan_fh)
scan_log = _scan_logger.info
scan_err = _scan_logger.error

AUTH_USER = config.AUTH_USER
AUTH_PASS = config.AUTH_PASS

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
    import threading
    threading.Thread(target=db.refresh_now_prices, daemon=True).start()
    signals = db.get_open_trades()
    return templates.TemplateResponse("open_trades.html", {
        "request": request,
        "signals": signals,
        "active_tab": "open_trades",
    })


@app.post("/ack/{signal_id}", response_class=HTMLResponse)
async def ack_trade(signal_id: str, request: Request):
    form = await request.form()
    try:
        price = float(form.get("entry_price", 0))
    except ValueError:
        return HTMLResponse("<span style='color:#ef4444;font-size:10px;'>Bad price</span>")
    if price <= 0:
        return HTMLResponse("<span style='color:#ef4444;font-size:10px;'>Enter price</span>")
    db.ack_signal(signal_id, price)
    return HTMLResponse("<span style='color:#22c55e;font-size:10px;'>✓ Opened</span>")


@app.post("/close-trade/{signal_id}", response_class=HTMLResponse)
def close_trade(signal_id: str):
    db.close_signal(signal_id)
    return HTMLResponse("<span style='color:#888;font-size:10px;'>Closed</span>")


@app.post("/scan", response_class=HTMLResponse)
def trigger_scan(request: Request):
    import threading
    def _run():
        scan_log("▶ Scan started (manual)")
        result = runner.run_scan_once("manual")
        scan_log(f"  {result}")
    threading.Thread(target=_run, daemon=True).start()
    return HTMLResponse("""<span style="color:#22c55e;font-size:11px;">
        ⟳ Scanning via Claude + TradingView MCP… results in ~30s
    </span>""")


@app.post("/enrich-ibkr", response_class=HTMLResponse)
def enrich_ibkr(request: Request):
    import threading
    def _run():
        scan_log("▶ IBKR enrichment started")
        result = runner.enrich_ibkr_signals()
        scan_log(f"  {result}")
    threading.Thread(target=_run, daemon=True).start()
    return HTMLResponse("<span style='color:#60a5fa;font-size:11px;'>⟳ Enriching with IBKR flow…</span>")


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
            prompt_file = config.PROMPTS_DIR / "analyze.md"
            prompt = prompt_file.read_text().replace("{TICKER}", ticker)
            use_claude = (
                config.claude_available()
                and Path(config.MCP_CONFIG).exists()
                and db.can_spend_credit()
            )
            if use_claude:
                db.record_credit("analyze", ticker)
                subprocess.run(
                    [config.CLAUDE_BIN, "-p", prompt,
                     "--mcp-config", config.MCP_CONFIG,
                     "--allowedTools",
                     "mcp__tradingview__multi_timeframe_analysis,"
                     "mcp__tradingview__multi_agent_analysis,"
                     "mcp__tradingview__financial_news,"
                     "mcp__claude_ai_Interactive_Brokers_IBKR__search_contracts,"
                     "mcp__claude_ai_Interactive_Brokers_IBKR__get_price_snapshot,"
                     "Bash"],
                    capture_output=True, text=True, timeout=config.CLAUDE_TIMEOUT,
                    env={**os.environ, "PYTHONPATH": str(config.FLOWSCANNER_HOME)}
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


@app.get("/health")
def health():
    try:
        with db.get_conn() as conn:
            conn.execute("SELECT 1")
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=503)


@app.get("/status", response_class=JSONResponse)
def status():
    return {
        "auto": state.auto_enabled(),
        "scan_requested": state.scan_requested(),
        "exit_check_requested": state.exit_check_requested(),
        "signal_count": len(db.get_signals()),
        "market_open": guards.market_is_open(),
        "credits_used_today": db.credits_used_today(),
        "credits_remaining": db.budget_remaining(),
        "daily_credit_cap": config.DAILY_CREDIT_CAP,
        "scan_interval_min": config.SCAN_INTERVAL_MIN,
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
    import time
    while True:
        try:
            if state.auto_enabled() and guards.market_is_open():
                interval_secs = max(60, config.SCAN_INTERVAL_MIN * 60)
                scan_log(f"▶ Auto-scan triggered (market open, interval {config.SCAN_INTERVAL_MIN}m)")
                result = runner.run_scan_once("auto")
                scan_log(f"  {result}")
                time.sleep(interval_secs)
            else:
                time.sleep(300)  # 5 min re-check
        except Exception as e:
            scan_err(f"Auto-scan loop error: {e}")
            time.sleep(60)


def _nightly_backup_loop():
    import time
    time.sleep(3600)  # wait 1h after startup before first backup attempt
    while True:
        try:
            db.backup_db()
            scan_log("✓ Nightly DB backup done")
        except Exception as e:
            scan_err(f"Backup error: {e}")
        time.sleep(86400)


import threading as _threading
_threading.Thread(target=_auto_scan_loop, daemon=True).start()
_threading.Thread(target=_nightly_backup_loop, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard:app", host="0.0.0.0", port=8765, reload=True)
