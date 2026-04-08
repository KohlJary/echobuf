"""Desktop notifications via notify-send."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def send_notification(
    summary: str,
    body: str = "",
    icon: str = "audio-x-generic",
    urgency: str = "low",
) -> None:
    """Send a desktop notification via notify-send.

    Fails silently if notify-send is not available — notifications
    are a nice-to-have, never a blocker.
    """
    notify_send = shutil.which("notify-send")
    if notify_send is None:
        log.debug("notify-send not found, skipping notification")
        return

    cmd = [
        notify_send,
        "--app-name=echobuf",
        f"--icon={icon}",
        f"--urgency={urgency}",
        summary,
    ]
    if body:
        cmd.append(body)

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        log.debug("Failed to send notification", exc_info=True)


def notify_save(path: Path, duration: float) -> None:
    """Notify the user that audio was saved."""
    send_notification(
        "Audio saved",
        f"{duration:.1f}s → {path.name}",
    )
