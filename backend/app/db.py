"""SQLite job store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_input TEXT NOT NULL,
    arxiv_id TEXT NOT NULL,
    target_pages INTEGER NOT NULL,
    writer_model TEXT NOT NULL,
    vision_model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT '',
    stages TEXT NOT NULL DEFAULT '[]',
    warnings TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    pdf_path TEXT,
    tex_path TEXT,
    captions_path TEXT,
    rounds INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_ALLOWED_FIELDS = {
    "status",
    "stage",
    "stages",
    "warnings",
    "error",
    "pdf_path",
    "tex_path",
    "captions_path",
    "rounds",
}


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _serialize(job: sqlite3.Row) -> dict:
    d = dict(job)
    for key in ("stages", "warnings"):
        d[key] = json.loads(d.get(key) or "[]")
    return d


def create_job(
    conn: sqlite3.Connection,
    arxiv_input: str,
    arxiv_id: str,
    target_pages: int,
    writer_model: str,
    vision_model: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (arxiv_input, arxiv_id, target_pages, writer_model, vision_model)"
        " VALUES (?, ?, ?, ?, ?)",
        (arxiv_input, arxiv_id, target_pages, writer_model, vision_model),
    )
    conn.commit()
    if cur.lastrowid is None:
        raise RuntimeError("sqlite failed to return lastrowid")
    return int(cur.lastrowid)


def update_job(conn: sqlite3.Connection, job_id: int, **fields) -> None:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unknown job fields: {sorted(unknown)}")
    sets = []
    vals: list = []
    for key, value in fields.items():
        if key in ("stages", "warnings"):
            value = json.dumps(value)
        sets.append(f"{key} = ?")
        vals.append(value)
    sets.append("updated_at = datetime('now')")
    vals.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _serialize(row) if row else None


def list_jobs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
    return [_serialize(r) for r in rows]
