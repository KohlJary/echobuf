"""Fixed-size circular buffer for audio samples."""

from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    """Preallocated circular buffer holding the last N seconds of audio.

    All audio is stored as float32 PCM. The buffer is thread-safe: the
    capture thread calls write() while the save handler calls snapshot().
    """

    def __init__(self, seconds: float, sample_rate: int, channels: int) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.capacity = int(seconds * sample_rate)
        self._buf = np.zeros((self.capacity, channels), dtype=np.float32)
        self._write = 0
        self._filled = 0
        self._lock = threading.Lock()

    def write(self, chunk: np.ndarray) -> None:
        """Append a chunk of audio samples to the buffer.

        chunk shape: (n_samples, channels), dtype float32.
        """
        n = chunk.shape[0]
        with self._lock:
            if n >= self.capacity:
                # Chunk larger than buffer — just keep the tail
                self._buf[:] = chunk[-self.capacity :]
                self._write = 0
                self._filled = self.capacity
                return

            end = self._write + n
            if end <= self.capacity:
                self._buf[self._write : end] = chunk
            else:
                first = self.capacity - self._write
                self._buf[self._write :] = chunk[:first]
                self._buf[: n - first] = chunk[first:]

            self._write = end % self.capacity
            self._filled = min(self._filled + n, self.capacity)

    def snapshot(self) -> np.ndarray:
        """Return a contiguous copy of the buffer in chronological order."""
        with self._lock:
            if self._filled == 0:
                return np.zeros((0, self.channels), dtype=np.float32)

            if self._filled < self.capacity:
                # Buffer hasn't wrapped yet
                return self._buf[: self._filled].copy()

            # Buffer has wrapped — read from write cursor to end, then start to cursor
            return np.concatenate(
                [self._buf[self._write :], self._buf[: self._write]]
            ).copy()

    @property
    def duration(self) -> float:
        """Current buffered duration in seconds."""
        with self._lock:
            return self._filled / self.sample_rate
