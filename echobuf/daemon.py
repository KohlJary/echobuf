"""echobuf daemon — capture loop and save handler."""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

import soundfile as sf

from .backend import AudioFormat, PulseBackend, PipeWireBackend, create_backend
from .config import Config
from .ipc import IPCServer
from .notify import notify_save
from .ringbuffer import RingBuffer
from .sources import PulsePerAppCapture, PipeWirePerAppCapture, list_sources
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
        self._backend_name = config.capture.backend
        self.backend = create_backend(self._backend_name)
        # Resolve "auto" to actual backend name for later decisions
        self._backend_name = "pipewire" if isinstance(self.backend, PipeWireBackend) else "pulse"

        self.output_dir = config.output.directory_path
        self._running = False
        self._paused = False
        self._capture_thread: threading.Thread | None = None
        self._ipc: IPCServer | None = None
        self._save_counter = 0
        self._per_app: PulsePerAppCapture | PipeWirePerAppCapture | None = None
        self._hotkey = None
        self._active_source = config.capture.source

    def start(self) -> None:
        """Start capture, IPC server, and block until stopped."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Handle per-app source if configured
        if self._active_source.startswith("app:"):
            self._setup_per_app(self._active_source[4:])
        else:
            self.backend.open(self.fmt)

        self._running = True

        # Signal handlers for clean shutdown
        signal.signal(signal.SIGINT, self._on_stop_signal)
        signal.signal(signal.SIGTERM, self._on_stop_signal)

        # Start IPC server
        self._ipc = IPCServer(self)
        self._ipc.start()

        # Start hotkey handler if configured
        if self.config.hotkey.binding:
            self._start_hotkey()

        # Start capture thread
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        log.info(
            "echobuf daemon running — backend=%s, buffer=%.0fs, rate=%dHz, channels=%d, source=%s, output=%s",
            self._backend_name,
            self.config.buffer.seconds,
            self.fmt.sample_rate,
            self.fmt.channels,
            self._active_source,
            self.output_dir,
        )
        log.info("Use `echobuf save` to capture, `echobuf status` to check, `echobuf quit` to stop")

        try:
            while self._running:
                time.sleep(0.5)
        finally:
            self._shutdown()

    def _start_hotkey(self) -> None:
        """Start the optional hotkey handler."""
        try:
            from .hotkey import HotkeyHandler
            self._hotkey = HotkeyHandler(self.config.hotkey.binding)
            self._hotkey.start()
        except (ImportError, RuntimeError) as e:
            log.warning("Could not start hotkey handler: %s", e)

    def _setup_per_app(self, app_name: str) -> None:
        """Set up per-app capture routing and open the backend on the capture source."""
        if self._backend_name == "pipewire":
            self._per_app = PipeWirePerAppCapture()
            target = self._per_app.setup(app_name)
            self.backend.open(self.fmt, device=target)
        else:
            self._per_app = PulsePerAppCapture()
            monitor = self._per_app.setup(app_name)
            self.backend.open(self.fmt, device=monitor)

    def _capture_loop(self) -> None:
        """Read audio from the backend and feed the ring buffer."""
        while self._running:
            try:
                chunk = self.backend.read()
                if not self._paused:
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
            source=self._active_source,
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

        if self.config.notifications.enabled:
            notify_save(out_path, duration)

        return out_path

    def pause(self) -> None:
        self._paused = True
        log.info("Capture paused")

    def resume(self) -> None:
        self._paused = False
        log.info("Capture resumed")

    @property
    def paused(self) -> bool:
        return self._paused

    def set_source(self, source_spec: str) -> None:
        """Switch capture source at runtime."""
        log.info("Switching source from %s to %s", self._active_source, source_spec)

        if self._per_app is not None:
            self._per_app.teardown()
            self._per_app = None

        self.backend.close()

        self.ring = RingBuffer(
            self.config.buffer.seconds,
            self.fmt.sample_rate,
            self.fmt.channels,
        )

        self._active_source = source_spec

        if source_spec.startswith("app:"):
            self._setup_per_app(source_spec[4:])
        else:
            self.backend.open(self.fmt)

        log.info("Now capturing from: %s", source_spec)

    def _on_stop_signal(self, signum: int, frame) -> None:
        log.info("Received signal %d, shutting down", signum)
        self._running = False

    def _shutdown(self) -> None:
        self._running = False
        if self._hotkey is not None:
            self._hotkey.stop()
        if self._ipc is not None:
            self._ipc.stop()
        if self._per_app is not None:
            self._per_app.teardown()
            self._per_app = None
        self.backend.close()
        log.info("Daemon stopped")
