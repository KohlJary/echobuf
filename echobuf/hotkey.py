"""Optional in-process hotkey handler via pynput.

Disabled by default. When [hotkey] binding is set in config, the daemon
grabs the key globally on startup and triggers saves via IPC.

This is a convenience layer for users who don't bind through their WM.
The recommended path is still `echobuf save` bound via WM/DE config.
"""

from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)

try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


def _parse_binding(binding: str) -> set:
    """Parse a binding string like '<ctrl>+<shift>+s' into pynput keys."""
    if not HAS_PYNPUT:
        raise RuntimeError("pynput is required for hotkey support (pip install pynput)")

    parts = [p.strip() for p in binding.lower().split("+")]
    keys = set()

    for part in parts:
        # Handle modifier keys
        if part in ("<ctrl>", "ctrl"):
            keys.add(keyboard.Key.ctrl_l)
        elif part in ("<shift>", "shift"):
            keys.add(keyboard.Key.shift)
        elif part in ("<alt>", "alt"):
            keys.add(keyboard.Key.alt_l)
        elif part in ("<super>", "super", "<cmd>", "cmd"):
            keys.add(keyboard.Key.cmd)
        elif len(part) == 1:
            keys.add(keyboard.KeyCode.from_char(part))
        elif part.startswith("<") and part.endswith(">"):
            key_name = part[1:-1]
            try:
                keys.add(getattr(keyboard.Key, key_name))
            except AttributeError:
                raise ValueError(f"Unknown key: {part}")
        else:
            try:
                keys.add(keyboard.KeyCode.from_char(part))
            except Exception:
                raise ValueError(f"Unknown key: {part}")

    return keys


class HotkeyHandler:
    """Grabs a global hotkey and triggers saves via IPC on press."""

    def __init__(self, binding: str) -> None:
        if not HAS_PYNPUT:
            raise RuntimeError("pynput is required for hotkey support (pip install pynput)")

        self._binding_str = binding
        self._target_keys = _parse_binding(binding)
        self._pressed: set = set()
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        """Start listening for the hotkey in a background thread."""
        wayland = os.environ.get("WAYLAND_DISPLAY")
        if wayland:
            log.warning(
                "Wayland detected — global hotkey grabs may not work. "
                "If the hotkey doesn't trigger, bind `echobuf save` via your compositor instead."
            )

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        log.info("Hotkey handler started: %s", self._binding_str)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key) -> None:
        self._pressed.add(self._normalize(key))
        if self._target_keys.issubset(self._pressed):
            log.info("Hotkey triggered: %s", self._binding_str)
            threading.Thread(target=self._trigger_save, daemon=True).start()

    def _on_release(self, key) -> None:
        self._pressed.discard(self._normalize(key))

    def _normalize(self, key):
        """Normalize key for comparison."""
        # Map right-side modifiers to left-side for matching
        if hasattr(key, 'value') and hasattr(keyboard.Key, 'ctrl_r'):
            mapping = {
                keyboard.Key.ctrl_r: keyboard.Key.ctrl_l,
                keyboard.Key.shift_r: keyboard.Key.shift,
                keyboard.Key.alt_r: keyboard.Key.alt_l,
            }
            return mapping.get(key, key)
        return key

    def _trigger_save(self) -> None:
        """Trigger a save via IPC."""
        from .ipc import ipc_send

        try:
            resp = ipc_send({"cmd": "save"})
            if resp.get("ok"):
                log.info("Hotkey save: %s", resp.get("path"))
            else:
                log.warning("Hotkey save failed: %s", resp.get("error"))
        except ConnectionError:
            log.warning("Hotkey save failed: daemon not reachable via IPC")
