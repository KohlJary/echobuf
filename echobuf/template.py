"""yt-dlp–style output template parser and filename sanitizer."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime


# Matches %(name)s, %(name)d, %(name)03d, %(name|default)s, etc.
_TOKEN_RE = re.compile(r"%\((\w+)(?:\|([^)]*))?\)([-+0-9.]*[sdifg])")

# Characters illegal in filenames on common filesystems
_UNSAFE_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Remove or replace characters unsafe for filenames.

    Preserves path separators (/) so templates can include directories.
    """
    # Normalize unicode
    name = unicodedata.normalize("NFC", name)
    # Replace unsafe chars with underscore
    name = _UNSAFE_RE.sub("_", name)
    # Collapse multiple underscores/spaces
    name = re.sub(r"[_ ]{2,}", "_", name)
    # Strip leading/trailing dots and spaces from each path component
    parts = name.split("/")
    parts = [p.strip(". ") for p in parts]
    return "/".join(p for p in parts if p)


def render_template(
    template: str,
    *,
    now: datetime | None = None,
    app: str = "unknown",
    source: str = "system",
    device: str = "default",
    duration: float = 0.0,
    counter: int = 0,
    label: str = "",
    ext: str = "wav",
    sanitize: bool = True,
) -> str:
    """Render an output path template with the given values.

    Supports %(token)s with printf-style formatting and %(token|default)s
    for fallback values.
    """
    if now is None:
        now = datetime.now()

    values = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H%M%S"),
        "timestamp": str(int(now.timestamp())),
        "iso": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "app": app,
        "source": source,
        "device": device,
        "duration": duration,
        "counter": counter,
        "label": label,
        "ext": ext,
    }

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        default = m.group(2)
        fmt_spec = m.group(3)

        value = values.get(name, "")

        # Apply default if value is empty
        if not value and default is not None:
            value = default

        # Format the value
        fmt_char = fmt_spec[-1]
        width_spec = fmt_spec[:-1]

        if fmt_char in ("d", "i"):
            try:
                formatted = format(int(float(value) if not isinstance(value, (int, float)) else value), f"{width_spec}d")
            except (ValueError, TypeError):
                formatted = str(value)
        elif fmt_char == "f":
            try:
                formatted = format(float(value) if not isinstance(value, float) else value, f"{width_spec}f")
            except (ValueError, TypeError):
                formatted = str(value)
        else:
            formatted = str(value)

        return formatted

    result = _TOKEN_RE.sub(_replace, template)

    if sanitize:
        result = sanitize_filename(result)

    return result
