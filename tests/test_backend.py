"""Tests for backend detection and factory."""

from unittest.mock import patch

import pytest

from echobuf.backend import (
    AudioFormat,
    PulseBackend,
    PipeWireBackend,
    create_backend,
    detect_backend,
)


class TestAudioFormat:
    def test_defaults(self):
        fmt = AudioFormat()
        assert fmt.sample_rate == 48000
        assert fmt.channels == 2

    def test_custom(self):
        fmt = AudioFormat(sample_rate=44100, channels=1)
        assert fmt.sample_rate == 44100
        assert fmt.channels == 1


class TestCreateBackend:
    def test_create_pulse(self):
        backend = create_backend("pulse")
        assert isinstance(backend, PulseBackend)

    def test_create_pipewire(self):
        backend = create_backend("pipewire")
        assert isinstance(backend, PipeWireBackend)

    def test_create_auto(self):
        backend = create_backend("auto")
        assert isinstance(backend, (PulseBackend, PipeWireBackend))

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            create_backend("alsa")


class TestDetectBackend:
    @patch("echobuf.backend.shutil.which")
    @patch("echobuf.backend.Path.exists")
    def test_detects_pipewire(self, mock_exists, mock_which):
        mock_exists.return_value = True
        mock_which.return_value = "/usr/bin/pw-record"
        assert detect_backend() == "pipewire"

    @patch("echobuf.backend.shutil.which")
    @patch("echobuf.backend.Path.exists")
    def test_falls_back_to_pulse(self, mock_exists, mock_which):
        mock_exists.return_value = False
        mock_which.side_effect = lambda cmd: "/usr/bin/parec" if cmd == "parec" else None
        assert detect_backend() == "pulse"

    @patch("echobuf.backend.shutil.which", return_value=None)
    @patch("echobuf.backend.Path.exists", return_value=False)
    def test_no_backend_raises(self, mock_exists, mock_which):
        with pytest.raises(RuntimeError, match="No audio backend"):
            detect_backend()


class TestPulseBackend:
    def test_read_before_open_raises(self):
        backend = PulseBackend()
        with pytest.raises(RuntimeError, match="not open"):
            backend.read()

    def test_close_without_open_is_safe(self):
        backend = PulseBackend()
        backend.close()  # Should not raise


class TestPipeWireBackend:
    def test_read_before_open_raises(self):
        backend = PipeWireBackend()
        with pytest.raises(RuntimeError, match="not open"):
            backend.read()

    def test_close_without_open_is_safe(self):
        backend = PipeWireBackend()
        backend.close()  # Should not raise
