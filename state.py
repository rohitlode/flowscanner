"""Lightweight file-based state flags shared between dashboard and scanner."""
import json
from pathlib import Path

_STATE_FILE = Path(__file__).parent / "data" / "state.json"


def _read() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {"auto": True, "scan_requested": False, "exit_check_requested": False}


def _write(d: dict):
    _STATE_FILE.write_text(json.dumps(d))


def auto_enabled() -> bool:
    return _read().get("auto", True)


def toggle_auto() -> bool:
    d = _read()
    d["auto"] = not d.get("auto", True)
    _write(d)
    return d["auto"]


def scan_requested() -> bool:
    return _read().get("scan_requested", False)


def set_scan_requested(val: bool):
    d = _read()
    d["scan_requested"] = val
    _write(d)


def exit_check_requested() -> bool:
    return _read().get("exit_check_requested", False)


def set_exit_check_requested(val: bool):
    d = _read()
    d["exit_check_requested"] = val
    _write(d)


def get_interval() -> str:
    return _read().get("interval", "Every 1 min")


def set_interval(val: str):
    d = _read()
    d["interval"] = val
    _write(d)
