"""Tests for IPC server and client."""

import json
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from echobuf.backend import AudioFormat
from echobuf.ringbuffer import RingBuffer


class FakeDaemon:
    """Minimal daemon stub for IPC testing."""

    def __init__(self):
        self.fmt = AudioFormat(sample_rate=48000, channels=2)
        self.ring = RingBuffer(seconds=5.0, sample_rate=48000, channels=2)
        self.output_dir = Path("/tmp/echobuf_test")
        self._running = True
        self._paused = False
        self._save_counter = 3
        self._active_source = "system"
        self._backend_name = "pipewire"
        self.config = MagicMock()

    @property
    def paused(self):
        return self._paused

    def save(self, label=None):
        self._save_counter += 1
        return Path(f"/tmp/test_{self._save_counter:03d}.wav")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def set_source(self, spec):
        self._active_source = spec


class TestIPCProtocol:
    """Test IPC server dispatch logic without actual socket I/O."""

    def setup_method(self):
        from echobuf.ipc import IPCServer
        self.daemon = FakeDaemon()
        self.server = IPCServer(self.daemon)

    def test_save_command(self):
        resp = self.server._dispatch({"cmd": "save"})
        assert resp["ok"] is True
        assert "path" in resp

    def test_save_with_label(self):
        resp = self.server._dispatch({"cmd": "save", "label": "test"})
        assert resp["ok"] is True

    def test_status_command(self):
        resp = self.server._dispatch({"cmd": "status"})
        assert resp["ok"] is True
        assert resp["running"] is True
        assert resp["paused"] is False
        assert resp["backend"] == "pipewire"
        assert resp["source"] == "system"
        assert resp["sample_rate"] == 48000
        assert resp["channels"] == 2
        assert "buffer_seconds" in resp
        assert "buffered" in resp
        assert "saves" in resp
        assert "output_dir" in resp

    def test_pause_command(self):
        resp = self.server._dispatch({"cmd": "pause"})
        assert resp["ok"] is True
        assert self.daemon._paused is True

    def test_resume_command(self):
        self.daemon._paused = True
        resp = self.server._dispatch({"cmd": "resume"})
        assert resp["ok"] is True
        assert self.daemon._paused is False

    def test_set_source_system(self):
        resp = self.server._dispatch({"cmd": "set_source", "type": "system"})
        assert resp["ok"] is True
        assert resp["source"] == "system"

    def test_set_source_app(self):
        resp = self.server._dispatch({"cmd": "set_source", "type": "app", "name": "firefox"})
        assert resp["ok"] is True
        assert resp["source"] == "app:firefox"

    def test_quit_command(self):
        resp = self.server._dispatch({"cmd": "quit"})
        assert resp["ok"] is True
        assert self.daemon._running is False

    def test_unknown_command(self):
        resp = self.server._dispatch({"cmd": "nonsense"})
        assert resp["ok"] is False
        assert "unknown" in resp["error"]

    def test_list_sources(self):
        resp = self.server._dispatch({"cmd": "list_sources"})
        assert resp["ok"] is True
        assert isinstance(resp["sources"], list)
        assert any(s["type"] == "system" for s in resp["sources"])


class TestIPCRoundTrip:
    """Test actual socket communication."""

    def test_send_receive(self):
        from echobuf.ipc import IPCServer, _socket_path

        daemon = FakeDaemon()
        server = IPCServer(daemon)
        server.start()

        try:
            sock_path = _socket_path()
            assert sock_path.exists()

            # Send a status command
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(sock_path))
            sock.sendall(json.dumps({"cmd": "status"}).encode() + b"\n")
            sock.shutdown(socket.SHUT_WR)

            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            sock.close()

            resp = json.loads(data.split(b"\n", 1)[0])
            assert resp["ok"] is True
            assert resp["running"] is True
        finally:
            server.stop()
