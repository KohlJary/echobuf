"""System tray icon — separate process, talks to the daemon via IPC."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image, ImageDraw

    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False


def _create_icon_image(color: str = "#4a9eff") -> Image.Image:
    """Generate a simple circular tray icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Filled circle with a small inner ring to suggest audio/buffer
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    draw.ellipse([20, 20, size - 20, size - 20], fill=(255, 255, 255, 200))
    draw.ellipse([26, 26, size - 26, size - 26], fill=color)
    return img


class TrayApp:
    """System tray icon that controls the echobuf daemon via IPC."""

    def __init__(self) -> None:
        if not HAS_PYSTRAY:
            raise RuntimeError("pystray and Pillow are required for the tray icon (pip install pystray Pillow)")
        self._icon: pystray.Icon | None = None
        self._paused = False

    def run(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Status", self._on_status, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Save now", self._on_save),
            pystray.MenuItem(
                lambda item: "Resume capture" if self._paused else "Pause capture",
                self._on_pause_toggle,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open save folder", self._on_open_folder),
            pystray.MenuItem("Edit config", self._on_edit_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit daemon", self._on_quit),
        )

        self._icon = pystray.Icon(
            name="echobuf",
            icon=_create_icon_image(),
            title="echobuf",
            menu=menu,
        )
        self._icon.run()

    def _ipc(self, msg: dict) -> dict | None:
        from .ipc import ipc_send

        try:
            return ipc_send(msg)
        except ConnectionError:
            self._show_notification("echobuf daemon is not running")
            return None

    def _show_notification(self, message: str) -> None:
        if self._icon is not None:
            self._icon.notify(message, "echobuf")

    def _on_status(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        resp = self._ipc({"cmd": "status"})
        if resp and resp.get("ok"):
            state = "paused" if resp.get("paused") else "recording"
            msg = (
                f"State: {state}\n"
                f"Buffer: {resp['buffered']}s / {resp['buffer_seconds']}s\n"
                f"Saves: {resp['saves']}"
            )
            self._show_notification(msg)

    def _on_save(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        resp = self._ipc({"cmd": "save"})
        if resp and resp.get("ok"):
            self._show_notification(f"Saved: {Path(resp['path']).name}")
        elif resp:
            self._show_notification(f"Save failed: {resp.get('error')}")

    def _on_pause_toggle(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        cmd = "resume" if self._paused else "pause"
        resp = self._ipc({"cmd": cmd})
        if resp and resp.get("ok"):
            self._paused = not self._paused
            # Update icon color
            color = "#888888" if self._paused else "#4a9eff"
            if self._icon is not None:
                self._icon.icon = _create_icon_image(color)

    def _on_open_folder(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        resp = self._ipc({"cmd": "status"})
        if resp and resp.get("ok"):
            output_dir = resp.get("output_dir", str(Path.home() / "samples"))
            try:
                subprocess.Popen(["xdg-open", output_dir])
            except OSError:
                self._show_notification("Could not open folder")

    def _on_edit_config(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        from .config import DEFAULT_CONFIG_PATH, DEFAULT_CONFIG_TEMPLATE

        config_path = DEFAULT_CONFIG_PATH
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(DEFAULT_CONFIG_TEMPLATE)

        try:
            subprocess.Popen(["xdg-open", str(config_path)])
        except OSError:
            self._show_notification(f"Could not open {config_path}")

    def _on_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._ipc({"cmd": "quit"})
        if self._icon is not None:
            self._icon.stop()


def run_tray() -> None:
    """Entry point for the tray icon process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    app = TrayApp()
    app.run()
