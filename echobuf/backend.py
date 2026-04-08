"""Audio capture backend abstraction with PulseAudio and PipeWire implementations."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class AudioFormat:
    sample_rate: int = 48000
    channels: int = 2


class AudioBackend(Protocol):
    """Common interface for audio capture backends."""

    def open(self, fmt: AudioFormat, device: str = "") -> None: ...
    def read(self) -> np.ndarray: ...
    def close(self) -> None: ...


class PulseBackend:
    """Capture system audio via parec (PulseAudio/PipeWire-Pulse)."""

    CHUNK_FRAMES = 4096

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._fmt: AudioFormat | None = None
        self._frame_bytes: int = 0

    def open(self, fmt: AudioFormat, device: str = "@DEFAULT_MONITOR@") -> None:
        parec = shutil.which("parec")
        if parec is None:
            raise RuntimeError("parec not found — install pulseaudio-utils or pipewire-pulse")

        self._fmt = fmt
        self._frame_bytes = fmt.channels * 4

        cmd = [
            parec,
            "--format=float32le",
            f"--rate={fmt.sample_rate}",
            f"--channels={fmt.channels}",
            f"--device={device}",
            "--raw",
        ]
        log.info("Starting capture (pulse): %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self) -> np.ndarray:
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
            log.info("Capture stopped (pulse)")


class PipeWireBackend:
    """Capture audio via pw-record (native PipeWire)."""

    CHUNK_FRAMES = 4096

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._fmt: AudioFormat | None = None
        self._frame_bytes: int = 0

    def open(self, fmt: AudioFormat, device: str = "") -> None:
        pw_record = shutil.which("pw-record")
        if pw_record is None:
            raise RuntimeError("pw-record not found — install pipewire")

        self._fmt = fmt
        self._frame_bytes = fmt.channels * 4  # f32 = 4 bytes

        cmd = [
            pw_record,
            "--format=f32",
            f"--rate={fmt.sample_rate}",
            f"--channels={fmt.channels}",
        ]

        if device:
            cmd.extend(["--target", device])

        cmd.append("-")  # stdout
        log.info("Starting capture (pipewire): %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self) -> np.ndarray:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("Backend not open")
        nbytes = self.CHUNK_FRAMES * self._frame_bytes
        data = self._proc.stdout.read(nbytes)
        if not data:
            raise RuntimeError("pw-record stream ended unexpectedly")
        assert self._fmt is not None
        samples = np.frombuffer(data, dtype=np.float32).copy()
        return samples.reshape(-1, self._fmt.channels)

    def close(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            self._proc.wait()
            self._proc = None
            log.info("Capture stopped (pipewire)")


def detect_backend() -> str:
    """Auto-detect the best available audio backend.

    Returns 'pipewire' if PipeWire is running, else 'pulse'.
    """
    # Check for PipeWire socket
    pw_socket = Path(f"/run/user/{__import__('os').getuid()}/pipewire-0")
    if pw_socket.exists() and shutil.which("pw-record"):
        log.info("Detected PipeWire (socket + pw-record available)")
        return "pipewire"

    if shutil.which("parec"):
        log.info("Using PulseAudio backend (parec available)")
        return "pulse"

    raise RuntimeError("No audio backend available — install pipewire or pulseaudio-utils")


def create_backend(name: str) -> PulseBackend | PipeWireBackend:
    """Create a backend instance by name."""
    if name == "auto":
        name = detect_backend()

    if name == "pipewire":
        return PipeWireBackend()
    elif name == "pulse":
        return PulseBackend()
    else:
        raise ValueError(f"Unknown backend: {name!r} (use 'auto', 'pipewire', or 'pulse')")
