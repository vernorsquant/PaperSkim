"""SQLite job store with forward migrations."""

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

# Applied to pre-v0.2 databases; no-ops on fresh ones (columns already in schema).
_MIGRATION_COLUMNS: dict[str, str] = {
    "source_kind": "TEXT NOT NULL DEFAULT 'arxiv'",
    "title": "TEXT NOT NULL DEFAULT ''",
    "source_pdf_path": "TEXT",
    "cost_usd": "REAL",
}

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
    "source_kind",
    "title",
    "source_pdf_path",
    "cost_usd",
}


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    for name, decl in _MIGRATION_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {decl}")


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
    source_kind: str = "arxiv",
    title: str = "",
) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (arxiv_input, arxiv_id, target_pages, writer_model,"
        " vision_model, source_kind, title)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            arxiv_input,
            arxiv_id,
            target_pages,
            writer_model,
            vision_model,
            source_kind,
            title,
        ),
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
