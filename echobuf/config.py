"""Configuration loading and defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "echobuf"


def _state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "echobuf"


DEFAULT_CONFIG_PATH = _config_dir() / "config.toml"
DEFAULT_OUTPUT_DIR = Path.home() / "samples"
DEFAULT_LOG_FILE = _state_dir() / "echobuf.log"
DEFAULT_TEMPLATE = "%(date)s/%(time)s_%(counter)03d.%(ext)s"


@dataclass
class BufferConfig:
    seconds: float = 10.0
    post_seconds: float = 0.0


@dataclass
class CaptureConfig:
    backend: str = "auto"
    source: str = "system"
    sample_rate: int = 48000
    channels: int = 2


@dataclass
class OutputConfig:
    directory: str = str(DEFAULT_OUTPUT_DIR)
    template: str = DEFAULT_TEMPLATE
    format: str = "wav"
    sanitize: bool = True

    @property
    def directory_path(self) -> Path:
        return Path(self.directory).expanduser()


@dataclass
class HotkeyConfig:
    binding: str = ""


@dataclass
class NotificationsConfig:
    enabled: bool = True
    sound: bool = True


@dataclass
class LoggingConfig:
    level: str = "info"
    file: str = str(DEFAULT_LOG_FILE)

    @property
    def file_path(self) -> Path:
        return Path(self.file).expanduser()


@dataclass
class Config:
    buffer: BufferConfig = field(default_factory=BufferConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _apply_dict(dc: object, data: dict) -> None:
    """Apply a dict of values onto a dataclass instance, ignoring unknown keys."""
    for key, value in data.items():
        if hasattr(dc, key):
            setattr(dc, key, value)


def load_config(path: Path | None = None) -> Config:
    """Load config from a TOML file, falling back to defaults."""
    cfg = Config()

    if path is None:
        path = DEFAULT_CONFIG_PATH

    if not path.exists():
        return cfg

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    section_map = {
        "buffer": cfg.buffer,
        "capture": cfg.capture,
        "output": cfg.output,
        "hotkey": cfg.hotkey,
        "notifications": cfg.notifications,
        "logging": cfg.logging,
    }

    for section_name, section_obj in section_map.items():
        if section_name in raw:
            _apply_dict(section_obj, raw[section_name])

    return cfg
