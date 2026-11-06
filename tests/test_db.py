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
