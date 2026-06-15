from __future__ import annotations
import os, shutil
from pathlib import Path

FLOWSCANNER_HOME = Path(os.environ.get("FLOWSCANNER_HOME", str(Path(__file__).parent)))
DATA_DIR    = FLOWSCANNER_HOME / "data"
LOGS_DIR    = FLOWSCANNER_HOME / "logs"
BACKUP_DIR  = DATA_DIR / "backups"
PROMPTS_DIR = FLOWSCANNER_HOME / "prompts"
REVIEWS_DIR = FLOWSCANNER_HOME / "reviews"

for _d in (DATA_DIR, LOGS_DIR, BACKUP_DIR, PROMPTS_DIR, REVIEWS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

CLAUDE_BIN     = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
MCP_CONFIG     = os.environ.get("MCP_CONFIG", str(FLOWSCANNER_HOME.parent / "Desktop/claude/config/claude_desktop_config.json"))
TV_MCP_SRC     = os.environ.get("TV_MCP_SRC", str(FLOWSCANNER_HOME.parent / "Projects/tradingview-mcp/src"))
AUTH_USER      = os.environ.get("DASH_USER", "rohit")
AUTH_PASS      = os.environ.get("DASH_PASS", "changeme123")
SCAN_INTERVAL_MIN   = max(1, int(os.environ.get("SCAN_INTERVAL_MIN", "5")))
DAILY_CREDIT_CAP    = int(os.environ.get("DAILY_CREDIT_CAP", "60"))
MARKET_TZ           = os.environ.get("MARKET_TZ", "US/Eastern")
CLAUDE_TIMEOUT      = int(os.environ.get("CLAUDE_TIMEOUT", "180"))
DB_PATH        = DATA_DIR / "signals.db"

UW_API_KEY     = os.environ.get("UW_API_KEY", "3eb19972-a08f-47db-be6e-a563489ac6ec")
UW_BASE_URL    = "https://api.unusualwhales.com"

# Premium thresholds for UW flow scoring
UW_SWEEP_PREMIUM_THRESHOLD  = 100_000   # $100k+ = institutional size
UW_LARGE_PREMIUM_THRESHOLD  = 500_000   # $500k+ = very large
UW_HIGH_VOL_OI_RATIO        = 2.0       # volume > 2× OI = opening rush

def claude_available() -> bool:
    return Path(CLAUDE_BIN).exists() if Path(CLAUDE_BIN).is_absolute() else bool(shutil.which(CLAUDE_BIN))
