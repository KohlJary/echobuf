"""Audio capture backend abstraction and PulseAudio implementation."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class AudioFormat:
    sample_rate: int = 48000
    channels: int = 2


class AudioBackend(Protocol):
    """Common interface for audio capture backends."""

    def open(self, fmt: AudioFormat) -> None: ...
    def read(self) -> np.ndarray: ...
    def close(self) -> None: ...


class PulseBackend:
    """Capture system audio via parec (PulseAudio/PipeWire-Pulse)."""

    CHUNK_FRAMES = 4096  # frames per read

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._fmt: AudioFormat | None = None
        self._frame_bytes: int = 0

    def open(self, fmt: AudioFormat, device: str = "@DEFAULT_MONITOR@") -> None:
        parec = shutil.which("parec")
        if parec is None:
            raise RuntimeError("parec not found — install pulseaudio-utils or pipewire-pulse")

        self._fmt = fmt
        # float32le = 4 bytes per sample
        self._frame_bytes = fmt.channels * 4

        cmd = [
            parec,
            "--format=float32le",
            f"--rate={fmt.sample_rate}",
            f"--channels={fmt.channels}",
            f"--device={device}",
            "--raw",
        ]
        log.info("Starting capture: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self) -> np.ndarray:
        """Read one chunk of audio. Blocks until data is available."""
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("Backend not open")

        nbytes = self.CHUNK_FRAMES * self._frame_bytes
        data = self._proc.stdout.read(nbytes)
        if not data:
            raise RuntimeError("parec stream ended unexpectedly")

        assert self._fmt is not None
        samples = np.frombuffer(data, dtype=np.float32).copy()
        return samples.reshape(-1, self._fmt.channels)

    def close(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            self._proc.wait()
            self._proc = None
            log.info("Capture stopped")
