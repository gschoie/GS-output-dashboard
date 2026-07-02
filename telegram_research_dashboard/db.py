from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def database_path() -> Path:
    return ROOT / os.getenv("DATABASE_PATH", "data/dashboard.db")


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize() -> None:
    with connect() as conn:
        conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reports)")}
        if "weekly_folder" not in columns:
            conn.execute("ALTER TABLE reports ADD COLUMN weekly_folder TEXT")
