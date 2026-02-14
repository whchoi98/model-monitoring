from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS probe_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    wall_clock_ms REAL,
    server_latency_ms REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_model_timestamp ON probe_results(model_id, timestamp);
"""


@dataclass
class ProbeResult:
    model_id: str
    model_name: str
    timestamp: str
    prompt: str
    status: str
    wall_clock_ms: Optional[float] = None
    server_latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    error_message: Optional[str] = None


class Database:
    def __init__(self, db_path: str = "monitoring.db"):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def insert_result(self, result: ProbeResult) -> None:
        self._conn.execute(
            """
            INSERT INTO probe_results
                (model_id, model_name, timestamp, prompt, status,
                 wall_clock_ms, server_latency_ms,
                 input_tokens, output_tokens, total_tokens, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.model_id,
                result.model_name,
                result.timestamp,
                result.prompt,
                result.status,
                result.wall_clock_ms,
                result.server_latency_ms,
                result.input_tokens,
                result.output_tokens,
                result.total_tokens,
                result.error_message,
            ),
        )
        self._conn.commit()

    def get_results(
        self,
        model_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list[dict]:
        query = "SELECT * FROM probe_results WHERE 1=1"
        params: list = []

        if model_id:
            query += " AND model_id = ?"
            params.append(model_id)
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)

        query += " ORDER BY timestamp DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_all_models(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT DISTINCT model_id, model_name FROM probe_results ORDER BY model_name"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_results(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT pr.*
            FROM probe_results pr
            INNER JOIN (
                SELECT model_id, MAX(timestamp) AS max_ts
                FROM probe_results
                GROUP BY model_id
            ) latest ON pr.model_id = latest.model_id AND pr.timestamp = latest.max_ts
            ORDER BY pr.model_name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()
