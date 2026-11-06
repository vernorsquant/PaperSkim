"""Single-worker job queue."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.app.settings import Settings


class JobQueue:
    def __init__(self, settings: Settings, db_path: Path):
        self.settings = settings
        self.db_path = db_path
        self._pending: list[int] = []
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
        if self._executor is not None:
            return
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._drain()

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
        try:
            run_job(job_id, self.settings, conn)
        finally:
            conn.close()
        self._drain()
