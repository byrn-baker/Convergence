#!/usr/bin/env python3
"""NetClaw REST Proxy — lightweight HTTP→CLI bridge.

Runs inside the NetClaw container alongside the OpenClaw gateway.
Accepts POST /api/agent {"message": "..."} and shells out to
`openclaw agent --agent main --message "..." --timeout <t>`,
returning the response as JSON.

Only one agent call runs at a time. Concurrent requests get an
immediate 503 "agent busy" response instead of queueing and timing out.
"""

import json
import logging
import os
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [netclaw-proxy] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("netclaw-proxy")

PORT = int(os.getenv("NETCLAW_PROXY_PORT", "18790"))
DEFAULT_TIMEOUT = int(os.getenv("NETCLAW_TIMEOUT", "900"))

_agent_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_agent_lock(agent: str) -> threading.Lock:
    with _locks_lock:
        if agent not in _agent_locks:
            _agent_locks[agent] = threading.Lock()
        return _agent_locks[agent]


def _run_openclaw(message: str, timeout: int, agent: str = "main") -> dict:
    """Run openclaw agent CLI and return parsed result."""
    cmd = [
        "openclaw", "agent",
        "--agent", agent,
        "--message", message,
        "--timeout", str(timeout),
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        stdout, stderr = proc.communicate(timeout=timeout + 30)
        stdout = stdout.strip()
        if proc.returncode != 0:
            return {"status": "error", "message": stderr.strip() or f"Exit code {proc.returncode}"}
        return {"status": "ok", "result": stdout}
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
            proc.wait()
        return {"status": "error", "message": f"Timeout after {timeout}s"}
    except Exception as e:
        if proc and proc.poll() is None:
            proc.kill()
        return {"status": "error", "message": str(e)}


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class ProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/agent":
            self._respond(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
            return
        message = data.get("message", "")
        if not message:
            self._respond(HTTPStatus.BAD_REQUEST, {"error": "message required"})
            return
        timeout = data.get("timeout", DEFAULT_TIMEOUT)

        agent = data.get("agent", "main")
        lock = _get_agent_lock(agent)

        # Try to acquire the lock without blocking — if this agent is busy, return 503
        acquired = lock.acquire(blocking=False)
        if not acquired:
            logger.info("Agent '%s' busy, rejecting: %.80s", agent, message)
            self._respond(HTTPStatus.SERVICE_UNAVAILABLE, {"status": "busy", "message": f"Agent '{agent}' is processing another request"})
            return

        try:
            logger.info("Request [%s]: %.120s (timeout=%ds)", agent, message, timeout)
            result = _run_openclaw(message, timeout, agent=agent)
            status = HTTPStatus.OK if result["status"] == "ok" else HTTPStatus.INTERNAL_SERVER_ERROR
            self._respond(status, result)
        finally:
            lock.release()

    def do_GET(self):
        if self.path == "/health":
            busy_agents = [a for a, l in _agent_locks.items() if l.locked()]
            self._respond(HTTPStatus.OK, {"status": "ok", "busy_agents": busy_agents})
            return
        self._respond(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _respond(self, status, body):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())
        except BrokenPipeError:
            logger.warning("Client disconnected before response was sent")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = ThreadedHTTPServer(("0.0.0.0", PORT), ProxyHandler)
    logger.info("NetClaw REST proxy listening on :%d", PORT)
    server.serve_forever()
