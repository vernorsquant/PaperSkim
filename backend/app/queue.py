"""Multi-worker job queue with stop/cancel support.

Jobs run `max_workers` at a time (default 2) so two papers condense in
parallel instead of one-at-a-time. `stop()` cancels every queued job that
has not started yet; already-running jobs are left to finish.
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.app.settings import Settings

CANCEL_ERROR = "cancelled — the queue was stopped"


class JobQueue:
    def __init__(self, settings: Settings, db_path: Path, max_workers: int = 2):
        self.settings = settings
        self.db_path = db_path
        self.max_workers = max(1, int(max_workers))
        self._pending: list[int] = []
        # jobs whose worker has actually started (not just been handed to the
        # executor); stop() must never cancel these.
        self._inflight: set[int] = set()
        # ids cancelled by stop() that a not-yet-started worker must skip.
        self._cancelled: set[int] = set()
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None

    def submit(self, job_id: int) -> int:
        with self._lock:
            self._pending.append(job_id)
            position = len(self._pending)
        if self._executor is not None:
            self._drain()
        return position

    def start(self) -> None:
        with self._lock:
            if self._executor is not None:
                return
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._drain()

    def stop(self) -> list[int]:
        """Cancel every queued job that has not started; return their ids.

        Running jobs keep running to completion — the pipeline has no safe
        mid-job abort, and the queue cannot halt a worker thread cleanly.
        """
        with self._lock:
            self._pending.clear()
            inflight = set(self._inflight)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cancelled: list[int] = []
        try:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE status = 'queued'"
            ).fetchall()
            for row in rows:
                jid = int(row["id"])
                if jid in inflight:
                    continue
                conn.execute(
                    "UPDATE jobs SET status = 'failed', stage = 'cancelled',"
                    " error = ?, updated_at = datetime('now') WHERE id = ?",
                    (CANCEL_ERROR, jid),
                )
                cancelled.append(jid)
                with self._lock:
                    self._cancelled.add(jid)
            conn.commit()
        finally:
            conn.close()
        return cancelled

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                job_id = self._pending.pop(0)
            executor = self._executor
            if executor is None:
                return
            executor.submit(self._worker, job_id)

    def _worker(self, job_id: int) -> None:
        from backend.pipeline.runner import run_job

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        skip = False
        with self._lock:
            if job_id in self._cancelled:
                # cancelled between being enqueued on the executor and now
                self._cancelled.discard(job_id)
                skip = True
            else:
                self._inflight.add(job_id)
        if skip:
            # outside the lock: _drain() re-acquires it (threading.Lock is
            # not reentrant — nesting here self-deadlocks)
            conn.close()
            self._drain()
            return
        try:
            try:
                run_job(job_id, self.settings, conn)
            finally:
                conn.close()
        finally:
            with self._lock:
                self._inflight.discard(job_id)
            # run_job swallows job-level errors, but a crash here (e.g. DB
            # failure) must never leave later jobs unprocessed.
            self._drain()
