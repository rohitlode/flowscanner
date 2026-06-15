from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            ticker TEXT NOT NULL,
            exchange TEXT NOT NULL,
            price REAL,
            change_pct REAL,
            volume_ratio REAL,
            flow_strategy TEXT,
            test_bucket TEXT,
            dte_bucket TEXT,
            otm_pct_range TEXT,
            contract_quality TEXT,
            oi_behavior TEXT,
            oi_prev INTEGER,
            oi_curr INTEGER,
            oi_delta INTEGER,
            contract_symbol TEXT,
            entry_price REAL,
            now_price REAL,
            direction TEXT,
            confidence INTEGER,
            analysis_summary TEXT,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS scan_runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            candidates INTEGER,
            signals_found INTEGER,
            exchange TEXT,
            status TEXT
        );

        CREATE TABLE IF NOT EXISTS backtest_results (
            id                TEXT PRIMARY KEY,
            ticker            TEXT NOT NULL UNIQUE,
            period            TEXT,
            best_strategy     TEXT,
            win_rate          REAL,
            n_trades          INTEGER,
            avg_return_pct    REAL,
            total_return_pct  REAL,
            macd_win_rate     REAL,
            macd_n_trades     INTEGER,
            macd_total_return REAL,
            rsi_win_rate      REAL,
            rsi_n_trades      INTEGER,
            rsi_total_return  REAL,
            vb_win_rate       REAL,
            vb_n_trades       INTEGER,
            vb_total_return   REAL,
            test_bucket       TEXT,
            run_at            TEXT
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            id              TEXT PRIMARY KEY,
            signal_id       TEXT NOT NULL,
            ticker          TEXT NOT NULL,
            opened_at       TEXT NOT NULL,
            closed_at       TEXT,
            entry_price     REAL NOT NULL,
            exit_price      REAL,
            quantity        REAL,
            contract_symbol TEXT,
            flow_strategy   TEXT,
            direction       TEXT,
            conviction_tier TEXT,
            test_bucket     TEXT,
            stop            REAL,
            tp1             REAL,
            tp2             REAL,
            pnl_pct         REAL,
            pnl_abs         REAL,
            exit_reason     TEXT,
            hold_minutes    REAL,
            is_win          INTEGER,
            features_json   TEXT,
            status          TEXT DEFAULT 'open'
        );

        CREATE TABLE IF NOT EXISTS credit_log (
            id       TEXT PRIMARY KEY,
            used_at  TEXT NOT NULL,
            kind     TEXT NOT NULL,
            detail   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_outcomes_status    ON outcomes(status, flow_strategy);
        CREATE INDEX IF NOT EXISTS idx_credit_log_used_at ON credit_log(used_at);
        CREATE INDEX IF NOT EXISTS idx_signals_status     ON signals(status, ticker);
        """)
        # Migrate: add new enrichment columns if they don't exist yet
        for col in [
            "ALTER TABLE signals ADD COLUMN sentiment TEXT",
            "ALTER TABLE signals ADD COLUMN rsi_signal TEXT",
            "ALTER TABLE signals ADD COLUMN macd_signal_dir TEXT",
            "ALTER TABLE signals ADD COLUMN price_vs_ema TEXT",
            "ALTER TABLE signals ADD COLUMN conviction_tier TEXT",
            "ALTER TABLE signals ADD COLUMN conviction_label TEXT",
            "ALTER TABLE signals ADD COLUMN sizing TEXT",
            "ALTER TABLE signals ADD COLUMN ah_fade_skip INTEGER DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN flow_patterns TEXT",
            "ALTER TABLE signals ADD COLUMN ibkr_flow TEXT",
            "ALTER TABLE signals ADD COLUMN uw_flow TEXT",
        ]:
            try:
                conn.execute(col)
            except Exception:
                pass  # columns already exist


def upsert_signal(data: dict) -> str:
    sig_id = data.get("id") or str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM signals WHERE ticker=? AND DATE(created_at)=DATE(?)",
            (data["ticker"], now)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE signals SET now_price=?, change_pct=?, volume_ratio=?,
                flow_strategy=?, test_bucket=?, oi_behavior=?, oi_prev=?, oi_curr=?,
                oi_delta=?, analysis_summary=?, confidence=?,
                sentiment=?, rsi_signal=?, macd_signal_dir=?, price_vs_ema=?,
                conviction_tier=?, conviction_label=?, sizing=?,
                ah_fade_skip=?, flow_patterns=?, ibkr_flow=?, uw_flow=?
                WHERE id=?
            """, (
                data.get("now_price"), data.get("change_pct"), data.get("volume_ratio"),
                data.get("flow_strategy"), data.get("test_bucket"), data.get("oi_behavior"),
                data.get("oi_prev"), data.get("oi_curr"), data.get("oi_delta"),
                data.get("analysis_summary"), data.get("confidence"),
                data.get("sentiment"), data.get("rsi_signal"),
                data.get("macd_signal_dir"), data.get("price_vs_ema"),
                data.get("conviction_tier"), data.get("conviction_label"),
                data.get("sizing"), data.get("ah_fade_skip"),
                str(data.get("flow_patterns") or ""),
                str(data.get("ibkr_flow") or "") or None,
                str(data.get("uw_flow") or "") or None,
                existing["id"]
            ))
            return existing["id"]
        else:
            conn.execute("""
                INSERT INTO signals (id, created_at, ticker, exchange, price, change_pct,
                volume_ratio, flow_strategy, test_bucket, dte_bucket, otm_pct_range,
                contract_quality, oi_behavior, oi_prev, oi_curr, oi_delta,
                contract_symbol, entry_price, now_price, direction, confidence,
                analysis_summary, sentiment, rsi_signal, macd_signal_dir, price_vs_ema,
                conviction_tier, conviction_label, sizing, ah_fade_skip, flow_patterns, ibkr_flow, uw_flow)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                sig_id, now, data["ticker"], data.get("exchange","NASDAQ"),
                data.get("price"), data.get("change_pct"), data.get("volume_ratio"),
                data.get("flow_strategy"), data.get("test_bucket","UNVALIDATED"),
                data.get("dte_bucket"), data.get("otm_pct_range"), data.get("contract_quality"),
                data.get("oi_behavior"), data.get("oi_prev"), data.get("oi_curr"), data.get("oi_delta"),
                data.get("contract_symbol"), data.get("entry_price"), data.get("now_price"),
                data.get("direction","long"), data.get("confidence"), data.get("analysis_summary"),
                data.get("sentiment"), data.get("rsi_signal"),
                data.get("macd_signal_dir"), data.get("price_vs_ema"),
                data.get("conviction_tier"), data.get("conviction_label"),
                data.get("sizing"), data.get("ah_fade_skip"),
                str(data.get("flow_patterns") or ""),
                str(data.get("ibkr_flow") or "") or None,
                str(data.get("uw_flow") or "") or None,
            ))
            return sig_id


def get_signals(limit=50):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM signals WHERE status='active'
            ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def upsert_backtest(r: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO backtest_results
              (id, ticker, period, best_strategy, win_rate, n_trades, avg_return_pct,
               total_return_pct, macd_win_rate, macd_n_trades, macd_total_return,
               rsi_win_rate, rsi_n_trades, rsi_total_return,
               vb_win_rate, vb_n_trades, vb_total_return, test_bucket, run_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ticker) DO UPDATE SET
              best_strategy=excluded.best_strategy, win_rate=excluded.win_rate,
              n_trades=excluded.n_trades, avg_return_pct=excluded.avg_return_pct,
              total_return_pct=excluded.total_return_pct,
              macd_win_rate=excluded.macd_win_rate, macd_n_trades=excluded.macd_n_trades,
              macd_total_return=excluded.macd_total_return,
              rsi_win_rate=excluded.rsi_win_rate, rsi_n_trades=excluded.rsi_n_trades,
              rsi_total_return=excluded.rsi_total_return,
              vb_win_rate=excluded.vb_win_rate, vb_n_trades=excluded.vb_n_trades,
              vb_total_return=excluded.vb_total_return,
              test_bucket=excluded.test_bucket, run_at=excluded.run_at
        """, (
            str(uuid.uuid4()), r["ticker"], r["period"], r["best_strategy"],
            r["win_rate"], r["n_trades"], r["avg_return_pct"], r["total_return_pct"],
            r["macd"]["win_rate"], r["macd"]["n_trades"], r["macd"]["total_return_pct"],
            r["rsi"]["win_rate"],  r["rsi"]["n_trades"],  r["rsi"]["total_return_pct"],
            r["vol_breakout"]["win_rate"], r["vol_breakout"]["n_trades"], r["vol_breakout"]["total_return_pct"],
            r["test_bucket"], r["run_at"],
        ))


def ack_signal(signal_id: str, entry_price: float, quantity=None, stop=None, tp1=None, tp2=None):
    import json
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE signals SET entry_price=?, now_price=? WHERE id=?",
                     (entry_price, entry_price, signal_id))
        existing = conn.execute(
            "SELECT id FROM outcomes WHERE signal_id=? AND status='open'", (signal_id,)
        ).fetchone()
        if existing:
            return existing["id"]
        sig = conn.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
        if not sig:
            return None
        sig = dict(sig)
        outcome_id = str(uuid.uuid4())
        conn.execute("""
            INSERT INTO outcomes
              (id, signal_id, ticker, opened_at, entry_price, quantity,
               flow_strategy, direction, conviction_tier, test_bucket,
               stop, tp1, tp2, features_json, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            outcome_id, signal_id, sig["ticker"], now, entry_price, quantity,
            sig.get("flow_strategy"), sig.get("direction"),
            sig.get("conviction_tier"), sig.get("test_bucket"),
            stop, tp1, tp2,
            json.dumps({k: sig[k] for k in sig.keys() if sig[k] is not None}),
            "open"
        ))
        return outcome_id


def close_signal(signal_id: str, exit_price: float | None = None, exit_reason: str = "manual"):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE signals SET status='closed' WHERE id=?", (signal_id,))
        row = conn.execute(
            "SELECT * FROM outcomes WHERE signal_id=? AND status='open'", (signal_id,)
        ).fetchone()
        if not row:
            return
        row = dict(row)
        ep = float(row["entry_price"])
        xp = float(exit_price) if exit_price else ep
        raw_pct = (xp - ep) / ep * 100 if ep else 0
        direction = row.get("direction") or "long"
        pnl_pct = raw_pct if direction == "long" else -raw_pct
        qty = float(row["quantity"]) if row.get("quantity") else 1.0
        pnl_abs = (xp - ep) * qty if direction == "long" else (ep - xp) * qty
        opened = datetime.fromisoformat(row["opened_at"])
        hold_min = (datetime.utcnow() - opened).total_seconds() / 60
        conn.execute("""
            UPDATE outcomes SET
              closed_at=?, exit_price=?, exit_reason=?,
              pnl_pct=?, pnl_abs=?, hold_minutes=?,
              is_win=?, status='closed'
            WHERE signal_id=? AND status='open'
        """, (now, xp, exit_reason, round(pnl_pct,4), round(pnl_abs,4),
              round(hold_min,1), 1 if pnl_pct > 0 else 0, signal_id))


def refresh_now_prices():
    """Update now_price for all open trades using yfinance."""
    import yfinance as yf
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, ticker FROM signals WHERE status='active' AND entry_price IS NOT NULL"
        ).fetchall()
    for row in rows:
        try:
            price = yf.Ticker(row["ticker"]).fast_info["last_price"]
            if price:
                with get_conn() as conn:
                    conn.execute("UPDATE signals SET now_price=? WHERE id=?", (price, row["id"]))
        except Exception:
            pass


def get_open_trades():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM signals
            WHERE status='active' AND entry_price IS NOT NULL
            ORDER BY created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def update_signal_test_bucket(ticker: str, test_bucket: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET test_bucket=? WHERE ticker=? AND status='active'",
            (test_bucket, ticker)
        )


def get_backtest_results():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_results ORDER BY run_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_scan_runs(limit=10):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_pipeline_stats():
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_runs,
                SUM(candidates) as total_candidates,
                SUM(signals_found) as total_signals,
                AVG(candidates) as avg_candidates,
                AVG(signals_found) as avg_signals
            FROM scan_runs
        """).fetchone()
        recent = conn.execute("""
            SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT 20
        """).fetchall()
    return dict(row) if row else {}, [dict(r) for r in recent]


def get_report_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) as n FROM signals WHERE status='active'").fetchone()
        by_strategy = conn.execute("""
            SELECT flow_strategy, COUNT(*) as n,
                   AVG(confidence) as avg_conf,
                   AVG(change_pct) as avg_chg
            FROM signals WHERE status='active' AND flow_strategy IS NOT NULL
            GROUP BY flow_strategy
        """).fetchall()
        by_bucket = conn.execute("""
            SELECT test_bucket, COUNT(*) as n
            FROM signals WHERE status='active'
            GROUP BY test_bucket
        """).fetchall()
        recent = conn.execute("""
            SELECT ticker, flow_strategy, test_bucket, confidence,
                   change_pct, volume_ratio, created_at
            FROM signals WHERE status='active'
            ORDER BY created_at DESC LIMIT 50
        """).fetchall()
    return {
        "total": dict(total)["n"] if total else 0,
        "by_strategy": [dict(r) for r in by_strategy],
        "by_bucket": [dict(r) for r in by_bucket],
        "recent": [dict(r) for r in recent],
    }


def record_credit(kind: str, detail: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO credit_log (id, used_at, kind, detail) VALUES (?,?,?,?)",
            (str(uuid.uuid4()), datetime.utcnow().isoformat(), kind, detail)
        )

def credits_used_today() -> int:
    today = datetime.utcnow().date().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM credit_log WHERE used_at >= ?", (today,)
        ).fetchone()
    return int(row["n"]) if row else 0

def budget_remaining() -> int:
    from config import DAILY_CREDIT_CAP
    return max(0, DAILY_CREDIT_CAP - credits_used_today())

def can_spend_credit() -> bool:
    return budget_remaining() > 0

def get_outcomes(status: str | None = None, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM outcomes WHERE status=? ORDER BY opened_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM outcomes ORDER BY opened_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]

def get_winrate_by(field: str) -> list[dict]:
    allowed = {"flow_strategy", "conviction_tier", "ticker", "test_bucket", "direction"}
    if field not in allowed:
        raise ValueError(f"field must be one of {allowed}")
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT {field},
                   COUNT(*) as n,
                   SUM(is_win) as wins,
                   ROUND(AVG(CAST(is_win AS FLOAT))*100, 1) as win_rate,
                   ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
                   ROUND(SUM(pnl_pct), 2) as total_pnl
            FROM outcomes WHERE status='closed'
            GROUP BY {field}
            ORDER BY win_rate DESC
        """).fetchall()
    return [dict(r) for r in rows]

def backup_db():
    from config import BACKUP_DIR
    today = datetime.utcnow().strftime("%Y%m%d")
    # skip if we already backed up today
    if any(BACKUP_DIR.glob(f"signals-{today}_*.db")):
        return
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"signals-{ts}.db"
    if dest.exists():
        return
    with get_conn() as conn:
        conn.execute(f"VACUUM INTO '{dest}'")
    backups = sorted(BACKUP_DIR.glob("signals-*.db"))
    for old in backups[:-14]:
        old.unlink(missing_ok=True)

def log_scan_run(exchange: str, candidates: int, signals_found: int, status: str = "done") -> str:
    run_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO scan_runs (id, started_at, candidates, signals_found, exchange, status)
            VALUES (?,?,?,?,?,?)
        """, (run_id, datetime.utcnow().isoformat(), candidates, signals_found, exchange, status))
    return run_id


init_db()
