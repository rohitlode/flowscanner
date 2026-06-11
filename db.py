import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "signals.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
                ah_fade_skip=?, flow_patterns=?
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
                conviction_tier, conviction_label, sizing, ah_fade_skip, flow_patterns)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                str(data.get("flow_patterns") or "")
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


def update_signal_test_bucket(ticker: str, test_bucket: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET test_bucket=? WHERE ticker=? AND status='active'",
            (test_bucket, ticker)
        )


def get_backtest_results():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_results ORDER BY win_rate DESC"
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


def log_scan_run(exchange: str, candidates: int, signals_found: int, status: str = "done") -> str:
    run_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO scan_runs (id, started_at, candidates, signals_found, exchange, status)
            VALUES (?,?,?,?,?,?)
        """, (run_id, datetime.utcnow().isoformat(), candidates, signals_found, exchange, status))
    return run_id


init_db()
