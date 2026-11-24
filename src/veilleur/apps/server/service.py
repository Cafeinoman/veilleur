# SPDX-License-Identifier: EUPL-1.2
"""`veilleur serve`: the WSGI application on a threaded server, and the worker thread for long jobs (spec EF-71,
§7.5). It listens on a local address, behind the TLS reverse proxy; it logs no request (ES-09)."""

from __future__ import annotations

import logging
import threading
from socketserver import ThreadingMixIn
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from veilleur.core.services import jobs
from veilleur.core.services.context import Core

from .wsgi import Api

log = logging.getLogger(__name__)
WORKER_PERIOD = 60.0


class Worker:
    """Runs pending jobs, those left by a previous process first; woken when a job is queued."""

    def __init__(self, core: Core, period: float = WORKER_PERIOD) -> None:
        self.core = core
        self.period = period
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="veilleur-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                jobs.run_pending(self.core)
            except Exception as exc:  # the worker must survive anything
                log.error("worker: %s", type(exc).__name__)
            self._wake.wait(self.period)


class _Server(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _Handler(WSGIRequestHandler):
    """Passes the raw request target to the application, logs nothing (no client address, ES-09)."""

    def get_environ(self) -> dict[str, Any]:
        environ: dict[str, Any] = super().get_environ()
        environ["REQUEST_URI"] = self.path
        environ.pop("REMOTE_ADDR", None)
        environ.pop("REMOTE_HOST", None)
        return environ

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(core: Core, host: str, port: int, *, language: str = "en") -> None:
    worker = Worker(core)
    api = Api(core, language=language, wake_worker=worker.wake)
    worker.start()
    with make_server(host, port, api, server_class=_Server, handler_class=_Handler) as server:
        try:
            server.serve_forever()
        finally:
            worker.stop()
