import sqlite3

import pytest

from backend.app.db import create_job, get_job, init_db, list_jobs, update_job


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "jobs.db")


def test_create_and_get_roundtrip(conn):
    jid = create_job(
        conn, "arxiv.org/abs/2401.12345", "2401.12345", 4, "w-model", "v-model"
    )
    job = get_job(conn, jid)
    assert job["arxiv_id"] == "2401.12345"
    assert job["target_pages"] == 4
    assert job["status"] == "queued"
    assert job["warnings"] == []


def test_update_unknown_field_raises(conn):
    jid = create_job(conn, "x", "2401.12345", 4, "w", "v")
    with pytest.raises(ValueError):
        update_job(conn, jid, not_a_field=1)


def test_update_fields(conn):
    jid = create_job(conn, "x", "2401.12345", 4, "w", "v")
    update_job(conn, jid, status="running", stage="fetch", warnings=["w1"])
    job = get_job(conn, jid)
    assert job["status"] == "running"
    assert job["stage"] == "fetch"
    assert job["warnings"] == ["w1"]


def test_list_orders_newest_first(conn):
    a = create_job(conn, "x", "1", 4, "w", "v")
    b = create_job(conn, "y", "2", 3, "w", "v")
    jobs = list_jobs(conn)
    assert [j["id"] for j in jobs] == [b, a]


def test_migration_from_legacy_schema(tmp_path):
    import sqlite3

    from backend.app.db import _SCHEMA, _MIGRATION_COLUMNS

    legacy = _SCHEMA.split("source_kind")[0]  # drop everything we added
    p = tmp_path / "legacy.db"
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    c.execute(legacy.rstrip().rstrip(";") + ";")
    c.commit()
    c.close()

    from pathlib import Path

    from backend.app.db import init_db

    conn = init_db(Path(p))
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    for name in _MIGRATION_COLUMNS:
        assert name in cols
    jid = create_job(conn, "in", "ref", 4, "w", "v", source_kind="doi", title="T")
    job = get_job(conn, jid)
    assert job["source_kind"] == "doi"
    assert job["title"] == "T"
    update_job(conn, jid, cost_usd=0.5, source_pdf_path="/tmp/x.pdf")
    assert get_job(conn, jid)["cost_usd"] == 0.5


def test_new_schema_has_v2_columns(tmp_path):
    from pathlib import Path

    conn = init_db(tmp_path / "fresh.db")
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    assert {"source_kind", "title", "source_pdf_path", "cost_usd"} <= cols


def test_fail_orphaned_jobs(conn):
    from backend.app.db import fail_orphaned_jobs

    running = create_job(conn, "x", "1", 4, "w", "v")
    queued = create_job(conn, "y", "2", 4, "w", "v")
    done = create_job(conn, "z", "3", 4, "w", "v")
    update_job(conn, running, status="running", stage="fetch")
    update_job(conn, done, status="done")

    n = fail_orphaned_jobs(conn)

    assert n == 2
    r = get_job(conn, running)
    assert r["status"] == "failed" and "restart" in r["error"].lower()
    q = get_job(conn, queued)
    assert q["status"] == "failed" and "restart" in q["error"].lower()
    assert get_job(conn, done)["status"] == "done"
