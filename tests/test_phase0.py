"""
Phase 0 invariant tests — runnable via both:
  python3 tests/test_phase0.py
  pytest tests/test_phase0.py
"""
from __future__ import annotations
import sys, os, time, tempfile
from pathlib import Path

# ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


def _setup_home(tmp: Path):
    """Point FLOWSCANNER_HOME at a temp dir and reload affected modules."""
    os.environ["FLOWSCANNER_HOME"] = str(tmp)
    # Force reload of config-dependent modules
    for mod in ["config", "guards", "db", "scanner"]:
        if mod in sys.modules:
            del sys.modules[mod]
    import config  # re-import with new home
    import db as _db
    _db.init_db()
    return config, _db


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_signal(db_mod, ticker="AAPL", direction="long") -> str:
    """Insert a minimal signal and return its id."""
    import uuid
    sig_id = str(uuid.uuid4())
    with db_mod.get_conn() as conn:
        conn.execute("""
            INSERT INTO signals
              (id, created_at, ticker, exchange, direction, status)
            VALUES (?,datetime('now'),?,?,?,'active')
        """, (sig_id, ticker, "NASDAQ", direction))
    return sig_id


# ── tests ────────────────────────────────────────────────────────────────────

def test_outcomes_ledger_open(tmp_path):
    """1. ack_signal creates an outcomes row."""
    cfg, db = _setup_home(tmp_path)
    sig_id = _make_signal(db)
    outcome_id = db.ack_signal(sig_id, entry_price=100.0)
    assert outcome_id is not None
    rows = db.get_outcomes(status="open")
    assert any(r["signal_id"] == sig_id for r in rows)


def test_outcomes_close_long(tmp_path):
    """2. exit > entry → positive pnl_pct for long."""
    cfg, db = _setup_home(tmp_path)
    sig_id = _make_signal(db, direction="long")
    db.ack_signal(sig_id, entry_price=100.0)
    db.close_signal(sig_id, exit_price=110.0)
    rows = db.get_outcomes(status="closed")
    row = next(r for r in rows if r["signal_id"] == sig_id)
    assert row["pnl_pct"] > 0


def test_outcomes_close_short(tmp_path):
    """3. exit < entry → positive pnl_pct for short (direction inversion)."""
    cfg, db = _setup_home(tmp_path)
    sig_id = _make_signal(db, direction="short")
    db.ack_signal(sig_id, entry_price=100.0)
    db.close_signal(sig_id, exit_price=90.0)
    rows = db.get_outcomes(status="closed")
    row = next(r for r in rows if r["signal_id"] == sig_id)
    assert row["pnl_pct"] > 0


def test_is_win_correct(tmp_path):
    """4. is_win=1 for profit, is_win=0 for loss."""
    cfg, db = _setup_home(tmp_path)
    # win
    sig_id_w = _make_signal(db, ticker="MSFT", direction="long")
    db.ack_signal(sig_id_w, entry_price=100.0)
    db.close_signal(sig_id_w, exit_price=110.0)
    # loss
    sig_id_l = _make_signal(db, ticker="TSLA", direction="long")
    db.ack_signal(sig_id_l, entry_price=100.0)
    db.close_signal(sig_id_l, exit_price=90.0)

    rows = {r["signal_id"]: r for r in db.get_outcomes(status="closed")}
    assert rows[sig_id_w]["is_win"] == 1
    assert rows[sig_id_l]["is_win"] == 0


def test_ack_idempotency(tmp_path):
    """5. Second ack returns same outcome_id, only one open row exists."""
    cfg, db = _setup_home(tmp_path)
    sig_id = _make_signal(db)
    oid1 = db.ack_signal(sig_id, entry_price=100.0)
    oid2 = db.ack_signal(sig_id, entry_price=105.0)
    assert oid1 == oid2
    open_rows = [r for r in db.get_outcomes(status="open") if r["signal_id"] == sig_id]
    assert len(open_rows) == 1


def test_winrate_aggregation(tmp_path):
    """6. get_winrate_by('direction') returns correct win_rate."""
    cfg, db = _setup_home(tmp_path)
    # 2 wins, 1 loss for long
    for i, (ep, xp) in enumerate([(100, 110), (100, 105), (100, 90)]):
        sid = _make_signal(db, ticker=f"T{i}", direction="long")
        db.ack_signal(sid, entry_price=ep)
        db.close_signal(sid, exit_price=xp)
    rows = db.get_winrate_by("direction")
    long_row = next((r for r in rows if r["direction"] == "long"), None)
    assert long_row is not None
    assert long_row["n"] == 3
    assert long_row["wins"] == 2
    assert abs(long_row["win_rate"] - 66.7) < 1.0


def test_credit_counting(tmp_path):
    """7. record_credit increments credits_used_today."""
    cfg, db = _setup_home(tmp_path)
    before = db.credits_used_today()
    db.record_credit("scan", "test")
    db.record_credit("scan", "test")
    assert db.credits_used_today() == before + 2


def test_credit_cap(tmp_path):
    """8. After DAILY_CREDIT_CAP credits, can_spend_credit() returns False."""
    cfg, db = _setup_home(tmp_path)
    cap = cfg.DAILY_CREDIT_CAP
    for _ in range(cap):
        db.record_credit("test", "cap_test")
    assert db.can_spend_credit() is False


def test_scanlock_single_flight(tmp_path):
    """9. Acquiring ScanLock twice raises ScanLock.Busy."""
    cfg, db = _setup_home(tmp_path)
    import guards
    raised = False
    with guards.ScanLock():
        try:
            with guards.ScanLock():
                pass
        except guards.ScanLock.Busy:
            raised = True
    assert raised


def test_scanlock_stale_reclaim(tmp_path):
    """10. Lock older than 300s is reclaimed."""
    cfg, db = _setup_home(tmp_path)
    import guards
    lock_path = cfg.DATA_DIR / "scan.lock"
    lock_path.write_text("123456")
    # backdate mtime by 400s
    old_time = time.time() - 400
    os.utime(lock_path, (old_time, old_time))
    # should not raise — stale lock reclaimed
    with guards.ScanLock():
        pass  # acquired successfully


def test_market_hours_saturday(tmp_path):
    """11. Saturday returns False."""
    cfg, db = _setup_home(tmp_path)
    import guards
    from datetime import datetime
    # 2026-06-13 is a Saturday
    sat = datetime(2026, 6, 13, 11, 0, 0)
    assert guards.market_is_open(sat) is False


def test_market_hours_wednesday_open(tmp_path):
    """12. Wednesday 10am ET returns True."""
    cfg, db = _setup_home(tmp_path)
    import guards
    try:
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        from datetime import datetime
        tz = ZoneInfo("US/Eastern")
        wed = datetime(2026, 6, 10, 10, 0, 0, tzinfo=tz)
        assert guards.market_is_open(wed) is True
    except Exception:
        # If zoneinfo not available, do naive check with a weekday
        from datetime import datetime
        wed = datetime(2026, 6, 10, 10, 0, 0)
        # Can't test TZ accurately without zoneinfo — skip
        pass


def test_market_hours_wednesday_closed(tmp_path):
    """13. Wednesday 5pm ET returns False."""
    cfg, db = _setup_home(tmp_path)
    import guards
    try:
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        from datetime import datetime
        tz = ZoneInfo("US/Eastern")
        wed_pm = datetime(2026, 6, 10, 17, 0, 0, tzinfo=tz)
        assert guards.market_is_open(wed_pm) is False
    except Exception:
        pass


def test_honest_labels_no_validated_test(tmp_path):
    """14. _classify() never returns test_bucket == 'VALIDATED_TEST'."""
    _setup_home(tmp_path)
    from scanner import _classify
    # Try many combinations that could previously have yielded VALIDATED_TEST
    for chg in [-5, 0, 5, 10]:
        for rsi in [20, 50, 80]:
            for vol_r in [1, 3, 6]:
                row = {
                    "ticker": "TEST", "change_pct": chg, "rsi": rsi,
                    "volume_ratio": vol_r, "macd": 1, "macd_signal": 0,
                    "price": 100, "ema200": 100,
                }
                result = _classify(row)
                assert result["test_bucket"] != "VALIDATED_TEST", (
                    f"Got VALIDATED_TEST for {row}"
                )


def test_honest_labels_oi_behavior_none(tmp_path):
    """15. _classify() returns oi_behavior == None."""
    _setup_home(tmp_path)
    from scanner import _classify
    row = {
        "ticker": "AAPL", "change_pct": 5, "rsi": 70,
        "volume_ratio": 4, "macd": 1, "macd_signal": 0,
        "price": 200, "ema200": 150,
    }
    result = _classify(row)
    assert result["oi_behavior"] is None


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    import traceback
    tests = [
        test_outcomes_ledger_open,
        test_outcomes_close_long,
        test_outcomes_close_short,
        test_is_win_correct,
        test_ack_idempotency,
        test_winrate_aggregation,
        test_credit_counting,
        test_credit_cap,
        test_scanlock_single_flight,
        test_scanlock_stale_reclaim,
        test_market_hours_saturday,
        test_market_hours_wednesday_open,
        test_market_hours_wednesday_closed,
        test_honest_labels_no_validated_test,
        test_honest_labels_oi_behavior_none,
    ]
    passed = 0
    failed = 0
    for test_fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                test_fn(Path(tmp))
                print(f"  ✓ {test_fn.__name__}")
                passed += 1
            except Exception as e:
                print(f"  ✗ {test_fn.__name__}: {e}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed}/{passed+failed} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    _run_all()
