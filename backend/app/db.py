"""
SQLite persistence. All SQL in the application lives in this file -- per
AGENTS.md, routes/controller/pipeline call these functions and never build
their own queries. Schema is docs/API_CONTRACT.md section 5 verbatim, plus the
`sessions` table and `session_id` foreign keys documented as a deviation in
docs/PLAN.md section 7 item 3.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger("glucosentry.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ts REAL NOT NULL,
    ended_ts REAL,
    device_id TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS ecg_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp REAL NOT NULL,
    sqi INTEGER NOT NULL,
    risk_score REAL,
    mode TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp REAL NOT NULL,
    risk_score REAL NOT NULL,
    acknowledged BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS foot_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp REAL NOT NULL,
    t_left REAL,
    t_right REAL,
    delta_t REAL,
    valid BOOLEAN,
    next_check_scheduled REAL,
    action TEXT
);

CREATE TABLE IF NOT EXISTS device_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp REAL NOT NULL,
    battery_pct INTEGER,
    mode TEXT,
    leads_off BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_ecg_ts ON ecg_windows(timestamp);
CREATE INDEX IF NOT EXISTS idx_ecg_session ON ecg_windows(session_id);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(timestamp);
CREATE INDEX IF NOT EXISTS idx_foot_ts ON foot_checks(timestamp);
"""


class Database:
    """Thin async wrapper around a single aiosqlite connection.

    One writer task owns this connection (docs/PLAN.md section 1 decision 5:
    "single writer task, batched commits" for the WAL risk in section 8's risk
    table) -- routes read through it too, but SQLite with WAL handles
    concurrent readers fine; it's concurrent *writers* that would contend.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("database ready at %s", self.path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() was not called")
        return self._conn

    # --- sessions -------------------------------------------------------

    async def start_session(self, device_id: Optional[str] = None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO sessions (started_ts, device_id) VALUES (?, ?)",
            (time.time(), device_id),
        )
        await self.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    async def end_session(self, session_id: int) -> None:
        await self.conn.execute(
            "UPDATE sessions SET ended_ts = ? WHERE id = ?", (time.time(), session_id)
        )
        await self.conn.commit()

    async def get_session(self, session_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return await cur.fetchone()

    # --- ecg_windows ------------------------------------------------------

    async def insert_ecg_window(
        self, session_id: int, timestamp: float, sqi: int, risk_score: Optional[float], mode: str
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO ecg_windows (session_id, timestamp, sqi, risk_score, mode) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, timestamp, sqi, risk_score, mode),
        )
        await self.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    async def risk_history(
        self, session_id: int, since_ts: float, max_points: int = 600
    ) -> list[aiosqlite.Row]:
        """Downsampled history for GET /api/risk/history (API_CONTRACT section 3).
        Uses a simple stride-based downsample: cheap, deterministic, and good
        enough at 600 points for a 24h line chart."""
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS n FROM ecg_windows "
            "WHERE session_id = ? AND timestamp >= ? AND risk_score IS NOT NULL",
            (session_id, since_ts),
        )
        row = await cur.fetchone()
        total = row["n"] if row else 0
        stride = max(1, total // max_points) if total else 1

        cur = await self.conn.execute(
            "SELECT timestamp, risk_score, mode, ROW_NUMBER() OVER (ORDER BY timestamp) AS rn "
            "FROM ecg_windows WHERE session_id = ? AND timestamp >= ? AND risk_score IS NOT NULL "
            "ORDER BY timestamp",
            (session_id, since_ts),
        )
        rows = await cur.fetchall()
        return [r for r in rows if (r["rn"] - 1) % stride == 0]

    async def mode_time_breakdown(self, session_id: int) -> dict[str, float]:
        """Approximates time-in-mode by counting windows per mode and
        multiplying by the nominal window duration. Good enough for the
        session summary; exact timing would need per-window durations, which
        the schema (deliberately, per docs/PLAN.md section 7 item 4) doesn't
        store at full resolution."""
        cur = await self.conn.execute(
            "SELECT mode, COUNT(*) as n, "
            "MIN(timestamp) as first_ts, MAX(timestamp) as last_ts "
            "FROM ecg_windows WHERE session_id = ? GROUP BY mode",
            (session_id,),
        )
        rows = await cur.fetchall()
        result: dict[str, float] = {}
        for r in rows:
            span = (r["last_ts"] - r["first_ts"]) if r["n"] > 1 else 0.0
            # Fall back to a 45s nominal window (SRD 3.1: 30-60s windows) when
            # a mode has only ever had a single window, so it isn't reported
            # as zero time.
            result[r["mode"]] = span if span > 0 else r["n"] * 45.0
        return result

    async def window_counts(self, session_id: int) -> tuple[int, int]:
        """Returns (total, rejected) window counts for the session summary."""
        cur = await self.conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN sqi = 0 THEN 1 ELSE 0 END) as rejected "
            "FROM ecg_windows WHERE session_id = ?",
            (session_id,),
        )
        row = await cur.fetchone()
        return (row["total"] or 0, row["rejected"] or 0)

    async def risk_stats(self, session_id: int) -> tuple[Optional[float], Optional[float]]:
        cur = await self.conn.execute(
            "SELECT AVG(risk_score) as mean, MAX(risk_score) as peak "
            "FROM ecg_windows WHERE session_id = ? AND risk_score IS NOT NULL",
            (session_id,),
        )
        row = await cur.fetchone()
        return (row["mean"], row["peak"])

    async def export_rows(self, session_id: int) -> list[aiosqlite.Row]:
        """One row per ECG window, with the nearest alert/foot-check/status
        reading attached, per docs/API_CONTRACT.md section 3 (GET
        /api/session/export).

        Two bugs were found and fixed while building this query, in order:

        1. A range-based LEFT JOIN (`ABS(diff) < 5.0`) was tried first and
           multiplied every row: device_status is inserted once per window
           (roughly 1 Hz), so that condition matches several device_status
           rows per ecg_window, not one -- 4 windows produced 16 export rows.

        2. Switching to a correlated scalar subquery with the outer
           reference in its `ORDER BY ABS(d.timestamp - w.timestamp) LIMIT 1`
           then failed with "no such column: w.timestamp" against this
           project's SQLite (3.35.5): that version resolves an outer-query
           column inside a subquery's WHERE or SELECT list, but not inside
           its ORDER BY. The fix is the nested form below: the inner-most
           subquery computes the distance as a plain column (`diff`) using
           the outer reference in its SELECT list, where correlation *is*
           resolved, and the enclosing `ORDER BY diff LIMIT 1` then sorts by
           that already-materialized column instead of needing correlation
           of its own.
        """
        cur = await self.conn.execute(
            """
            SELECT
                w.timestamp AS timestamp,
                w.mode AS mode,
                w.sqi AS sqi,
                w.risk_score AS risk_score,
                (SELECT alert_id FROM (
                    SELECT a.id AS alert_id, ABS(a.timestamp - w.timestamp) AS diff
                    FROM alerts a WHERE a.session_id = w.session_id
                 ) WHERE diff < 1.0 ORDER BY diff LIMIT 1) AS alert_id,
                (SELECT acknowledged FROM (
                    SELECT a.acknowledged AS acknowledged, ABS(a.timestamp - w.timestamp) AS diff
                    FROM alerts a WHERE a.session_id = w.session_id
                 ) WHERE diff < 1.0 ORDER BY diff LIMIT 1) AS acknowledged,
                (SELECT foot_delta_t FROM (
                    SELECT f.delta_t AS foot_delta_t, ABS(f.timestamp - w.timestamp) AS diff
                    FROM foot_checks f WHERE f.session_id = w.session_id
                 ) WHERE diff < 1.0 ORDER BY diff LIMIT 1) AS foot_delta_t,
                (SELECT foot_valid FROM (
                    SELECT f.valid AS foot_valid, ABS(f.timestamp - w.timestamp) AS diff
                    FROM foot_checks f WHERE f.session_id = w.session_id
                 ) WHERE diff < 1.0 ORDER BY diff LIMIT 1) AS foot_valid,
                (SELECT battery_pct FROM (
                    SELECT d.battery_pct AS battery_pct, ABS(d.timestamp - w.timestamp) AS diff
                    FROM device_status d WHERE d.session_id = w.session_id
                 ) ORDER BY diff LIMIT 1) AS battery_pct
            FROM ecg_windows w
            WHERE w.session_id = ?
            ORDER BY w.timestamp
            """,
            (session_id,),
        )
        return await cur.fetchall()

    # --- alerts -----------------------------------------------------------

    async def insert_alert(self, session_id: int, timestamp: float, risk_score: float) -> int:
        cur = await self.conn.execute(
            "INSERT INTO alerts (session_id, timestamp, risk_score) VALUES (?, ?, ?)",
            (session_id, timestamp, risk_score),
        )
        await self.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    async def acknowledge_alert(self, alert_id: int) -> bool:
        cur = await self.conn.execute(
            "UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def alert_counts(self, session_id: int) -> tuple[int, int]:
        cur = await self.conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN acknowledged THEN 1 ELSE 0 END) as acked "
            "FROM alerts WHERE session_id = ?",
            (session_id,),
        )
        row = await cur.fetchone()
        return (row["total"] or 0, row["acked"] or 0)

    # --- foot_checks --------------------------------------------------------

    async def insert_foot_check(
        self,
        session_id: int,
        timestamp: float,
        t_left: Optional[float],
        t_right: Optional[float],
        delta_t: Optional[float],
        valid: bool,
        next_check_scheduled: Optional[float],
        action: str,
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO foot_checks "
            "(session_id, timestamp, t_left, t_right, delta_t, valid, next_check_scheduled, action) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, timestamp, t_left, t_right, delta_t, valid, next_check_scheduled, action),
        )
        await self.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    async def foot_history(self, session_id: int, limit: int = 50) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM foot_checks WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit),
        )
        return await cur.fetchall()

    async def latest_foot_check(self, session_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM foot_checks WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1",
            (session_id,),
        )
        return await cur.fetchone()

    async def foot_check_count(self, session_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) as n FROM foot_checks WHERE session_id = ?", (session_id,)
        )
        row = await cur.fetchone()
        return row["n"] if row else 0

    # --- device_status ------------------------------------------------------

    async def insert_device_status(
        self, session_id: int, timestamp: float, battery_pct: int, mode: str, leads_off: bool
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO device_status (session_id, timestamp, battery_pct, mode, leads_off) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, timestamp, battery_pct, mode, leads_off),
        )
        await self.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid


def row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)
