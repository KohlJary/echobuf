"""IPC server and client over Unix domain socket.

Protocol: line-delimited JSON. Each message is a single JSON object
terminated by a newline. The server sends a JSON response back.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .daemon import Daemon

log = logging.getLogger(__name__)


def _socket_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(runtime_dir) / "echobuf.sock"


class IPCServer:
    """Listens on a Unix socket and dispatches commands to the daemon."""

    def __init__(self, daemon: Daemon) -> None:
        self._daemon = daemon
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        sock_path = _socket_path()
        # Remove stale socket
        if sock_path.exists():
            sock_path.unlink()

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(sock_path))
        self._sock.listen(5)
        self._sock.settimeout(1.0)
        self._running = True

        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        log.info("IPC listening on %s", sock_path)

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        sock_path = _socket_path()
        if sock_path.exists():
            sock_path.unlink()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                assert self._sock is not None
                conn, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            line = data.split(b"\n", 1)[0]
            if not line:
                return

            msg = json.loads(line)
            response = self._dispatch(msg)
            conn.sendall(json.dumps(response).encode() + b"\n")
        except Exception:
            log.exception("IPC handler error")
            try:
                conn.sendall(json.dumps({"ok": False, "error": "internal error"}).encode() + b"\n")
            except OSError:
                pass
        finally:
            conn.close()

    def _dispatch(self, msg: dict[str, Any]) -> dict[str, Any]:
        cmd = msg.get("cmd", "")

        if cmd == "save":
            label = msg.get("label")
            path = self._daemon.save(label=label)
            if path is not None:
                return {"ok": True, "path": str(path)}
            return {"ok": False, "error": "buffer empty"}

        elif cmd == "status":
            return {
                "ok": True,
                "running": True,
                "paused": self._daemon.paused,
                "source": self._daemon._active_source,
                "buffer_seconds": self._daemon.ring.capacity / self._daemon.fmt.sample_rate,
                "buffered": round(self._daemon.ring.duration, 1),
                "sample_rate": self._daemon.fmt.sample_rate,
                "channels": self._daemon.fmt.channels,
                "saves": self._daemon._save_counter,
                "output_dir": str(self._daemon.output_dir),
            }

        elif cmd == "list_sources":
            from .sources import PerAppCapture
            pac = PerAppCapture()
            sources = pac.list_sources()
            return {
                "ok": True,
                "sources": [
                    {"type": s.type, "name": s.name, "binary": s.app_binary}
                    for s in sources
                ],
            }

        elif cmd == "pause":
            self._daemon.pause()
            return {"ok": True}

        elif cmd == "resume":
            self._daemon.resume()
            return {"ok": True}

        elif cmd == "set_source":
            source_type = msg.get("type", "system")
            if source_type == "system":
                spec = "system"
            else:
                name = msg.get("name", "")
                spec = f"app:{name}"
            try:
                self._daemon.set_source(spec)
                return {"ok": True, "source": spec}
            except RuntimeError as e:
                return {"ok": False, "error": str(e)}

        elif cmd == "quit":
            log.info("Quit requested via IPC")
            self._daemon._running = False
            return {"ok": True}

        else:
            return {"ok": False, "error": f"unknown command: {cmd}"}


def ipc_send(msg: dict[str, Any]) -> dict[str, Any]:
    """Send a command to the daemon and return the response."""
    sock_path = _socket_path()
    if not sock_path.exists():
        raise ConnectionError("echobuf daemon is not running (no socket)")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(sock_path))
        sock.sendall(json.dumps(msg).encode() + b"\n")
        sock.shutdown(socket.SHUT_WR)

        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        return json.loads(data.split(b"\n", 1)[0])
    finally:
        sock.close()
