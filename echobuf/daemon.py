"""echobuf daemon — capture loop and save handler."""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

import soundfile as sf

from .backend import AudioFormat, PulseBackend
from .config import Config
from .ipc import IPCServer
from .ringbuffer import RingBuffer
from .template import render_template

log = logging.getLogger(__name__)


class Daemon:
    """Core daemon: runs the capture loop and handles save triggers."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.fmt = AudioFormat(
            sample_rate=config.capture.sample_rate,
            channels=config.capture.channels,
        )
        self.ring = RingBuffer(
            config.buffer.seconds,
            config.capture.sample_rate,
            config.capture.channels,
        )
        self.backend = PulseBackend()
        self.output_dir = config.output.directory_path
        self._running = False
        self._capture_thread: threading.Thread | None = None
        self._ipc: IPCServer | None = None
        self._save_counter = 0

    def start(self) -> None:
        """Start capture, IPC server, and block until stopped."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.backend.open(self.fmt)
        self._running = True

        # Signal handlers for clean shutdown
        signal.signal(signal.SIGINT, self._on_stop_signal)
        signal.signal(signal.SIGTERM, self._on_stop_signal)

        # Start IPC server
        self._ipc = IPCServer(self)
        self._ipc.start()

        # Start capture thread
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        log.info(
            "echobuf daemon running — buffer=%.0fs, rate=%dHz, channels=%d, output=%s",
            self.config.buffer.seconds,
            self.fmt.sample_rate,
            self.fmt.channels,
            self.output_dir,
        )
        log.info("Use `echobuf save` to capture, `echobuf status` to check, `echobuf quit` to stop")

        try:
            while self._running:
                time.sleep(0.5)
        finally:
            self._shutdown()

    def _capture_loop(self) -> None:
        """Read audio from the backend and feed the ring buffer."""
        while self._running:
            try:
                chunk = self.backend.read()
                self.ring.write(chunk)
            except RuntimeError:
                if self._running:
                    log.exception("Capture error")
                break

    def save(self, label: str | None = None) -> Path | None:
        """Snapshot the buffer and write it to a WAV file."""
        audio = self.ring.snapshot()
        if audio.shape[0] == 0:
            log.warning("Buffer is empty, nothing to save")
            return None

        self._save_counter += 1
        duration = audio.shape[0] / self.fmt.sample_rate

        filename = render_template(
            self.config.output.template,
            now=datetime.now(),
            source=self.config.capture.source,
            duration=duration,
            counter=self._save_counter,
            label=label or "",
            ext=self.config.output.format,
            sanitize=self.config.output.sanitize,
        )

        out_path = self.output_dir / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(out_path), audio, self.fmt.sample_rate, subtype="PCM_16")
        log.info("Saved %.1fs of audio to %s", duration, out_path)
        return out_path

    def _on_stop_signal(self, signum: int, frame) -> None:
        log.info("Received signal %d, shutting down", signum)
        self._running = False

    def _shutdown(self) -> None:
        self._running = False
        if self._ipc is not None:
            self._ipc.stop()
        self.backend.close()
        log.info("Daemon stopped")
