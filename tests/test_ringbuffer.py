"""Tests for the ring buffer."""

import threading

import numpy as np
import pytest

from echobuf.ringbuffer import RingBuffer


class TestRingBuffer:
    def test_empty_buffer(self):
        rb = RingBuffer(seconds=1.0, sample_rate=100, channels=2)
        assert rb.duration == 0.0
        snap = rb.snapshot()
        assert snap.shape == (0, 2)
        assert snap.dtype == np.float32

    def test_partial_fill(self):
        rb = RingBuffer(seconds=1.0, sample_rate=100, channels=2)
        chunk = np.ones((50, 2), dtype=np.float32)
        rb.write(chunk)
        assert rb.duration == 0.5
        snap = rb.snapshot()
        assert snap.shape == (50, 2)
        np.testing.assert_array_equal(snap, chunk)

    def test_exact_fill(self):
        rb = RingBuffer(seconds=1.0, sample_rate=100, channels=1)
        chunk = np.arange(100, dtype=np.float32).reshape(-1, 1)
        rb.write(chunk)
        assert rb.duration == 1.0
        snap = rb.snapshot()
        assert snap.shape == (100, 1)
        np.testing.assert_array_equal(snap, chunk)

    def test_wraparound(self):
        rb = RingBuffer(seconds=1.0, sample_rate=100, channels=1)
        # Write 60 samples, then 60 more — should wrap
        chunk1 = np.ones((60, 1), dtype=np.float32)
        chunk2 = np.full((60, 1), 2.0, dtype=np.float32)
        rb.write(chunk1)
        rb.write(chunk2)
        assert rb.duration == 1.0
        snap = rb.snapshot()
        assert snap.shape == (100, 1)
        # First 40 should be 2.0 (from chunk2's tail that wrapped)
        # Wait — let's think: after chunk1 (60 samples), cursor at 60.
        # chunk2 writes 60: positions 60-99 get first 40, positions 0-19 get last 20.
        # Snapshot reads from cursor (20) forward: positions 20-99, then 0-19
        # Positions 20-59: chunk1 values (1.0), positions 60-99: chunk2 first 40 (2.0),
        # positions 0-19: chunk2 last 20 (2.0)
        # So: 40 ones, then 60 twos
        np.testing.assert_array_equal(snap[:40], np.ones((40, 1)))
        np.testing.assert_array_equal(snap[40:], np.full((60, 1), 2.0))

    def test_oversize_chunk(self):
        """A chunk larger than the buffer should keep only the tail."""
        rb = RingBuffer(seconds=1.0, sample_rate=100, channels=1)
        big = np.arange(200, dtype=np.float32).reshape(-1, 1)
        rb.write(big)
        assert rb.duration == 1.0
        snap = rb.snapshot()
        assert snap.shape == (100, 1)
        # Should contain the last 100 values
        np.testing.assert_array_equal(snap, big[100:])

    def test_multiple_small_writes(self):
        rb = RingBuffer(seconds=0.1, sample_rate=100, channels=2)
        # 10-sample capacity, write 3 samples at a time
        for i in range(5):
            chunk = np.full((3, 2), float(i), dtype=np.float32)
            rb.write(chunk)
        # Capacity is 10, wrote 15 total — last 10 should be in buffer
        snap = rb.snapshot()
        assert snap.shape == (10, 2)
        assert snap.dtype == np.float32

    def test_snapshot_is_copy(self):
        """Snapshot should be independent of the buffer."""
        rb = RingBuffer(seconds=1.0, sample_rate=100, channels=1)
        chunk = np.ones((50, 1), dtype=np.float32)
        rb.write(chunk)
        snap = rb.snapshot()
        snap[:] = 999.0
        # Original buffer should be unchanged
        snap2 = rb.snapshot()
        np.testing.assert_array_equal(snap2, chunk)

    def test_mono(self):
        rb = RingBuffer(seconds=0.5, sample_rate=100, channels=1)
        chunk = np.ones((50, 1), dtype=np.float32)
        rb.write(chunk)
        assert rb.snapshot().shape == (50, 1)

    def test_thread_safety(self):
        """Concurrent writes and snapshots shouldn't crash."""
        rb = RingBuffer(seconds=0.5, sample_rate=1000, channels=2)
        errors = []

        def writer():
            try:
                for _ in range(100):
                    chunk = np.random.randn(50, 2).astype(np.float32)
                    rb.write(chunk)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    snap = rb.snapshot()
                    assert snap.ndim == 2
                    assert snap.shape[1] == 2
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread safety errors: {errors}"
