from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from astrbot.api import logger


class KlogDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        conn = self.connect()
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur

    def executemany(self, sql: str, seq_of_params: Iterable[Iterable[Any]]) -> None:
        conn = self.connect()
        conn.executemany(sql, [tuple(p) for p in seq_of_params])
        conn.commit()

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        cur = self.connect().execute(sql, tuple(params))
        return cur.fetchone()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        cur = self.connect().execute(sql, tuple(params))
        return list(cur.fetchall())

    def migrate(self) -> None:
        conn = self.connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
              version INTEGER PRIMARY KEY
            );
            """
        )
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;").fetchone()
        current = int(row["version"]) if row else 0

        if current < 1:
            self._migrate_v1(conn)
            conn.execute("INSERT INTO schema_version(version) VALUES (1);")
            conn.commit()

    def _migrate_v1(self, conn: sqlite3.Connection) -> None:
        logger.info("klog: migrating schema to v1")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS plans (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              name TEXT NOT NULL,
              alias TEXT,
              note TEXT,
              start_at TEXT,
              done_at TEXT,
              archived_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(user_id, name),
              UNIQUE(alias)
            );

            CREATE TABLE IF NOT EXISTS stages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              plan_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              note TEXT,
              plan_start_at TEXT NOT NULL,
              plan_end_at TEXT NOT NULL,
              start_at TEXT,
              done_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(plan_id, name),
              FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              stage_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              note TEXT,
              order_no INTEGER,
              state TEXT NOT NULL,
              progress INTEGER NOT NULL,
              start_at TEXT,
              done_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(stage_id, name),
              FOREIGN KEY(stage_id) REFERENCES stages(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS worklogs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              task_id INTEGER NOT NULL,
              type TEXT NOT NULL,
              minutes INTEGER,
              note TEXT,
              progress INTEGER,
              created_at TEXT NOT NULL,
              FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS timers (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              task_id INTEGER NOT NULL,
              start_at TEXT NOT NULL,
              end_at TEXT,
              remind_minutes INTEGER,
              next_remind_at TEXT,
              unified_msg_origin TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_timers_active ON timers(user_id, end_at);

            CREATE TABLE IF NOT EXISTS dailies (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              date TEXT NOT NULL,
              plan_id INTEGER,
              done TEXT,
              block TEXT,
              next TEXT,
              note TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(user_id, date, plan_id),
              FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
              user_id TEXT NOT NULL,
              key TEXT NOT NULL,
              value TEXT,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(user_id, key)
            );
            """
        )

