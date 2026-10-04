import sqlite3
import threading
from contextlib import closing
from datetime import date
from pathlib import Path

DEEP_LIMIT_PER_DAY = 3
MODES = ("auto", "fast", "deep")

_DB = Path(__file__).resolve().parent.parent / "DB" / "limits.sqlite"
_DB.parent.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS deep_usage ("
        "user_id TEXT, day TEXT, count INTEGER, PRIMARY KEY (user_id, day))"
    )
    c.execute("CREATE TABLE IF NOT EXISTS user_mode (user_id TEXT PRIMARY KEY, mode TEXT)")
    return c


def _period() -> str:
    return date.today().isoformat()   # use a constant like "total" for a lifetime limit


def deep_left(user_id) -> int:
    with _lock, closing(_conn()) as c:
        row = c.execute(
            "SELECT count FROM deep_usage WHERE user_id=? AND day=?", (str(user_id), _period())
        ).fetchone()
    return max(0, DEEP_LIMIT_PER_DAY - (row[0] if row else 0))


def add_deep_use(user_id) -> None:
    with _lock, closing(_conn()) as c:
        c.execute(
            "INSERT INTO deep_usage (user_id, day, count) VALUES (?, ?, 1) "
            "ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1",
            (str(user_id), _period()),
        )
        c.commit()


def try_use_deep(user_id) -> int | None:
    """Atomically consume one deep run. Returns runs left after it, or None if the limit is reached."""
    with _lock, closing(_conn()) as c:
        row = c.execute(
            "SELECT count FROM deep_usage WHERE user_id=? AND day=?", (str(user_id), _period())
        ).fetchone()
        used = row[0] if row else 0
        if used >= DEEP_LIMIT_PER_DAY:
            return None
        c.execute(
            "INSERT INTO deep_usage (user_id, day, count) VALUES (?, ?, 1) "
            "ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1",
            (str(user_id), _period()),
        )
        c.commit()
    return DEEP_LIMIT_PER_DAY - used - 1


def refund_deep_use(user_id) -> None:
    """Give one run back (used when a deep run failed)."""
    with _lock, closing(_conn()) as c:
        c.execute(
            "UPDATE deep_usage SET count = MAX(count - 1, 0) WHERE user_id=? AND day=?",
            (str(user_id), _period()),
        )
        c.commit()


def get_mode(user_id) -> str:
    with _lock, closing(_conn()) as c:
        row = c.execute("SELECT mode FROM user_mode WHERE user_id=?", (str(user_id),)).fetchone()
    return row[0] if row and row[0] in MODES else "auto"


def set_mode(user_id, mode: str) -> None:
    if mode not in MODES:
        return
    with _lock, closing(_conn()) as c:
        c.execute(
            "INSERT INTO user_mode (user_id, mode) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET mode = excluded.mode",
            (str(user_id), mode),
        )
        c.commit()
