"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import pytest

from echobuf.config import Config, load_config, DEFAULT_TEMPLATE


class TestConfigDefaults:
    def test_default_buffer(self):
        cfg = Config()
        assert cfg.buffer.seconds == 10.0
        assert cfg.buffer.post_seconds == 0.0

    def test_default_capture(self):
        cfg = Config()
        assert cfg.capture.backend == "auto"
        assert cfg.capture.source == "system"
        assert cfg.capture.sample_rate == 48000
        assert cfg.capture.channels == 2

    def test_default_output(self):
        cfg = Config()
        assert cfg.output.format == "wav"
        assert cfg.output.sanitize is True
        assert cfg.output.template == DEFAULT_TEMPLATE

    def test_default_hotkey_empty(self):
        cfg = Config()
        assert cfg.hotkey.binding == ""

    def test_default_notifications(self):
        cfg = Config()
        assert cfg.notifications.enabled is True
        assert cfg.notifications.sound is True


class TestLoadConfig:
    def test_missing_file_returns_defaults(self):
        cfg = load_config(Path("/nonexistent/path/config.toml"))
        assert cfg.buffer.seconds == 10.0
        assert cfg.capture.sample_rate == 48000

    def test_partial_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[buffer]\nseconds = 30\n')
            f.flush()
            cfg = load_config(Path(f.name))
            assert cfg.buffer.seconds == 30.0
            # Other sections should be defaults
            assert cfg.capture.sample_rate == 48000
            assert cfg.output.format == "wav"
            Path(f.name).unlink()

    def test_full_config(self):
        content = """
[buffer]
seconds = 60
post_seconds = 5

[capture]
backend = "pulse"
source = "app:firefox"
sample_rate = 44100
channels = 1

[output]
directory = "/tmp/my_samples"
template = "%(label)s.%(ext)s"
format = "wav"
sanitize = false

[hotkey]
binding = "<ctrl>+<shift>+s"

[notifications]
enabled = false
sound = false

[logging]
level = "debug"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(content)
            f.flush()
            cfg = load_config(Path(f.name))
            assert cfg.buffer.seconds == 60
            assert cfg.buffer.post_seconds == 5
            assert cfg.capture.backend == "pulse"
            assert cfg.capture.source == "app:firefox"
            assert cfg.capture.sample_rate == 44100
            assert cfg.capture.channels == 1
            assert cfg.output.directory == "/tmp/my_samples"
            assert cfg.output.sanitize is False
            assert cfg.hotkey.binding == "<ctrl>+<shift>+s"
            assert cfg.notifications.enabled is False
            assert cfg.logging.level == "debug"
            Path(f.name).unlink()

    def test_unknown_keys_ignored(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[buffer]\nseconds = 5\nfake_key = "hello"\n')
            f.flush()
            cfg = load_config(Path(f.name))
            assert cfg.buffer.seconds == 5.0
            assert not hasattr(cfg.buffer, "fake_key")
            Path(f.name).unlink()

    def test_output_directory_path_expands_tilde(self):
        cfg = Config()
        cfg.output.directory = "~/my_samples"
        path = cfg.output.directory_path
        assert "~" not in str(path)
        assert str(path).endswith("my_samples")
