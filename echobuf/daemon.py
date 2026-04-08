"""echobuf daemon — capture loop and save handler."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

import soundfile as sf

from .backend import AudioFormat, PulseBackend
from .ringbuffer import RingBuffer

log = logging.getLogger(__name__)

# Default output directory for v0.1
DEFAULT_OUTPUT_DIR = Path.home() / "samples"


class Daemon:
    """Core daemon: runs the capture loop and handles save triggers."""

    def __init__(
        self,
        buffer_seconds: float = 10.0,
        sample_rate: int = 48000,
        channels: int = 2,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
    ) -> None:
        self.fmt = AudioFormat(sample_rate=sample_rate, channels=channels)
        self.ring = RingBuffer(buffer_seconds, sample_rate, channels)
        self.backend = PulseBackend()
        self.output_dir = output_dir
        self._running = False
        self._capture_thread: threading.Thread | None = None
        self._save_counter = 0

    def start(self) -> None:
        """Start capture and block until stopped."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.backend.open(self.fmt)
        self._running = True

        # Register SIGUSR1 as save trigger, SIGINT/SIGTERM for shutdown
        signal.signal(signal.SIGUSR1, self._on_save_signal)
        signal.signal(signal.SIGINT, self._on_stop_signal)
        signal.signal(signal.SIGTERM, self._on_stop_signal)

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        log.info(
            "echobuf daemon running — buffer=%.0fs, rate=%dHz, channels=%d, output=%s",
            self.ring.capacity / self.fmt.sample_rate,
            self.fmt.sample_rate,
            self.fmt.channels,
            self.output_dir,
        )
        log.info("Send SIGUSR1 (kill -USR1 %d) or run `echobuf save` to capture", os.getpid())

        # Write PID file so `echobuf save` can find us
        pid_path = _pid_path()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

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
        now = datetime.now()
        filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{self._save_counter:03d}.wav"
        if label:
            filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{label}_{self._save_counter:03d}.wav"

        out_path = self.output_dir / now.strftime("%Y-%m-%d") / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(out_path), audio, self.fmt.sample_rate, subtype="PCM_16")
        duration = audio.shape[0] / self.fmt.sample_rate
        log.info("Saved %.1fs of audio to %s", duration, out_path)
        return out_path

    def _on_save_signal(self, signum: int, frame) -> None:
        # Run save on a worker thread so we don't block the signal handler
        threading.Thread(target=self.save, daemon=True).start()

    def _on_stop_signal(self, signum: int, frame) -> None:
        log.info("Received signal %d, shutting down", signum)
        self._running = False

    def _shutdown(self) -> None:
        self._running = False
        self.backend.close()
        pid_path = _pid_path()
        if pid_path.exists():
            pid_path.unlink()
        log.info("Daemon stopped")


def _pid_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(runtime_dir) / "echobuf.pid"
