# echobuf — design specification

**Status:** draft v0.1
**Target platform:** Linux (PipeWire and PulseAudio)
**Language:** Python 3.11+
**License:** TBD

---

## 1. Concept

A background daemon that continuously records system audio output into a fixed-size rolling buffer in RAM. When the user presses a global hotkey, the current contents of the buffer are flushed to a `.wav` file on disk.

Think of it as Nvidia ShadowPlay's instant replay, but for audio. Use case: you're listening to music, a podcast, a stream, a game — something cool happens — you hit the hotkey and that moment is captured without having to have been recording in advance.

## 2. Goals and non-goals

**Goals**

- Zero-friction sampling of "the thing I just heard"
- Negligible CPU and RAM footprint when idle
- Sensible behavior across both PipeWire and PulseAudio systems
- Configurable file output paths via a yt-dlp–style template system
- Optional capture scope: full system mix or a specific application
- Run as a user systemd service with a tray icon for control

**Non-goals (for v1)**

- Editing, trimming, or normalizing captured audio
- Format support beyond WAV (FLAC/Opus may come later)
- Cross-platform support (macOS/Windows) — Linux only
- A full DAW integration or plugin layer
- Network streaming or remote capture

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────┐
│                    echobuf daemon                       │
│                                                         │
│  ┌──────────────┐   ┌────────────┐   ┌──────────────┐   │
│  │ Audio Source │──▶│   Ring     │──▶│    Writer    │   │
│  │   (capture)  │   │  Buffer    │   │  (on trigger)│   │
│  └──────────────┘   └────────────┘   └──────────────┘   │
│         ▲                                  ▲            │
│         │                                  │            │
│  ┌──────┴───────┐                   ┌──────┴───────┐    │
│  │   Backend    │                   │   Hotkey     │    │
│  │ Auto-detect  │                   │  Listener    │    │
│  │ (PW or PA)   │                   │              │    │
│  └──────────────┘                   └──────────────┘    │
│                                                         │
│  ┌────────────────────────────────────────────────┐     │
│  │             IPC (Unix socket)                  │     │
│  └────────────────────────────────────────────────┘     │
│         ▲                                               │
└─────────┼───────────────────────────────────────────────┘
          │
   ┌──────┴──────┐
   │  Tray icon  │  (separate process, optional)
   └─────────────┘
```

The daemon is the core. The tray icon is a separate process that talks to the daemon over a Unix domain socket; the daemon runs fine without it.

## 4. Components

### 4.1 Audio source / backend abstraction

A small abstraction layer with two implementations behind a common interface:

```python
class AudioBackend(Protocol):
    def open(self, source: SourceSpec, fmt: AudioFormat) -> None: ...
    def read(self) -> np.ndarray: ...   # blocking, returns one chunk
    def close(self) -> None: ...
    def list_sources(self) -> list[SourceInfo]: ...
```

**Backend selection at startup**

1. Probe for PipeWire by checking for `pipewire-pulse` socket and `pw-cli` availability
2. If found, use PipeWire backend
3. Else fall back to PulseAudio backend
4. Allow override via `--backend pipewire|pulse` flag or config

**PipeWire backend**

- Use `pipewire-python` bindings if mature enough at build time, else shell out to `pw-record` and read raw PCM from its stdout
- For "full system" capture: record from the default sink's monitor
- For "per-app" capture: create a virtual sink, route the target app's stream into it via `pw-link`, record its monitor
- Reasoning: PipeWire's graph model makes per-app capture clean once you understand it, but the Python ecosystem is still catching up

**PulseAudio backend**

- Use `pulsectl` (Python bindings to libpulse) for source enumeration and stream control
- Use `parec` subprocess for the actual capture (raw PCM on stdout, easy to consume)
- For "full system": record from `@DEFAULT_MONITOR@`
- For "per-app": use `module-loopback` or create a null sink and reroute the target sink-input

Both backends emit chunks of `np.float32` PCM data at a fixed sample rate and channel count negotiated at open time.

### 4.2 Ring buffer

A fixed-size circular buffer holding the last N seconds of audio. Implemented as a preallocated NumPy array with a write cursor; no per-chunk allocation in the hot path.

```python
class RingBuffer:
    def __init__(self, seconds: float, sample_rate: int, channels: int):
        self.capacity = int(seconds * sample_rate)
        self._buf = np.zeros((self.capacity, channels), dtype=np.float32)
        self._write = 0
        self._filled = 0
        self._lock = threading.Lock()

    def write(self, chunk: np.ndarray) -> None: ...
    def snapshot(self) -> np.ndarray:
        """Return a contiguous copy of the buffer in chronological order."""
```

Snapshot copies the buffer under the lock so the writer thread can keep going while the snapshot is being serialized to disk. For 60 seconds of 48kHz stereo float32 that's about 22 MB — trivially cheap to copy.

### 4.3 Capture thread

A single dedicated thread:

```
loop:
    chunk = backend.read()
    ringbuffer.write(chunk)
```

That's it. No processing, no filtering, no analysis. Stays out of the way.

### 4.4 Trigger handler

Triggered by either a hotkey event or an IPC command. On trigger:

1. Snapshot the ring buffer (atomic copy)
2. If `post_buffer_seconds > 0`, continue capturing for that long and append to the snapshot
3. Resolve the output path from the template
4. Create parent directories if needed
5. Write the WAV file via `soundfile.write()`
6. Emit a notification (libnotify) and/or play a confirmation blip
7. Log the save

Saves run on a worker thread so a slow disk doesn't block capture.

### 4.5 Hotkey handling

The primary interface for triggering a save is the `echobuf save` CLI command, which sends an IPC message to the daemon. This is the documented, supported, recommended path for all users — the daemon itself does not need to know that input devices exist.

**Why this is the primary path:**

- Linux global hotkeys are a mess: X11 needs `XGrabKey`, Wayland deliberately denies global grabs to arbitrary clients, and every compositor handles bindings differently. Punting input to the WM/DE sidesteps all of it.
- Users with tiling WMs (i3, sway, hyprland, awesome, etc.) already have rich, expressive binding configurations and don't want a second system fighting them for keys.
- It enables compositional tricks the daemon could never offer on its own (interactive labeling via rofi/dmenu, chords, modes, release-on-key bindings, etc.).
- It keeps the daemon headless and trivially testable.

**Example bindings**

i3 / sway:
```
bindsym $mod+Shift+s exec --no-startup-id echobuf save
bindsym $mod+Shift+d exec --no-startup-id echobuf save --label dialogue
bindsym $mod+Shift+m exec --no-startup-id echobuf save --label "$(rofi -dmenu -p tag)"
```

GNOME: bind `echobuf save` to a custom shortcut in Settings → Keyboard → Custom Shortcuts.

KDE: bind via System Settings → Shortcuts → Custom Shortcuts.

**Built-in hotkey handler (opt-in convenience layer)**

For users who don't want to touch their WM config, the daemon can optionally grab a hotkey itself using `pynput`. This is disabled by default — empty binding in the config means no grab attempt, no startup warning, no interaction with the user's existing key setup.

```toml
[hotkey]
# Optional. If set, echobuf will try to grab this key globally on startup.
# Leave empty if you bind via your WM/DE (recommended for tiling WM users).
binding = ""
```

When set, the handler:

- On X11: grabs the key via `pynput` (which uses python-xlib under the hood)
- On Wayland: attempts the grab, logs a clear warning if the compositor refuses, and points the user at the docs for binding via their DE

The built-in handler is a thin convenience wrapper that internally calls the same IPC save path as the CLI. There is exactly one code path for "trigger a save," and it goes through the socket.

### 4.6 IPC

Unix domain socket at `$XDG_RUNTIME_DIR/echobuf.sock`. Line-delimited JSON commands:

```json
{"cmd": "save"}
{"cmd": "save", "label": "drum_fill"}
{"cmd": "status"}
{"cmd": "set_buffer_seconds", "value": 30}
{"cmd": "set_source", "type": "app", "name": "spotify"}
{"cmd": "list_sources"}
{"cmd": "quit"}
```

Used by both the CLI and the tray icon. Keeps the daemon headless and dependency-light.

### 4.7 Tray icon

Separate process. Uses `pystray` (cross-toolkit) or a Qt tray via `PyQt6`/`PySide6` if a richer menu is needed.

**Menu items:**

- Status indicator (recording / paused / error)
- Save now
- Pause / resume capture
- Switch source → submenu listing available sinks and active sink-inputs
- Open save folder
- Settings... (opens config file in `$EDITOR`)
- Quit daemon

The tray talks to the daemon over the Unix socket. If the daemon isn't running, the tray offers to start it.

### 4.8 systemd service

A user unit at `~/.config/systemd/user/echobuf.service`:

```ini
[Unit]
Description=echobuf audio replay buffer
After=pipewire.service pulseaudio.service
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/echobuf daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

The tray icon is launched separately, typically via the desktop environment's autostart, not by the systemd unit, so that the daemon remains useful in headless contexts and the tray icon's lifecycle is bound to the graphical session.

## 5. Configuration

Config file at `$XDG_CONFIG_HOME/echobuf/config.toml` (default `~/.config/echobuf/config.toml`).

```toml
[buffer]
seconds = 10              # rolling buffer length
post_seconds = 2          # additional seconds captured after hotkey press

[capture]
backend = "auto"          # auto | pipewire | pulse
source = "system"         # system | app:<name> | sink:<id>
sample_rate = 48000
channels = 2

[output]
directory = "~/samples"
template = "%(date)s/%(app)s/%(time)s_%(counter)03d.%(ext)s"
format = "wav"            # wav only in v1
sanitize = true           # apply yt-dlp-style filename sanitization

[hotkey]
# Optional in-process hotkey grab. Leave empty (the default) if you bind
# `echobuf save` via your WM/DE — that's the recommended path for tiling
# WM users and avoids fighting your existing keybinds.
binding = ""

[notifications]
enabled = true
sound = true              # play a short blip on save

[logging]
level = "info"
file = "~/.local/state/echobuf/echobuf.log"
```

### 5.1 Output template tokens

Modeled directly on yt-dlp's output template system. The template is parsed once at startup and validated.

| Token | Meaning | Example |
|---|---|---|
| `%(date)s` | Local date, ISO | `2026-04-08` |
| `%(time)s` | Local time, `HHMMSS` | `143052` |
| `%(timestamp)s` | Unix epoch | `1744128652` |
| `%(iso)s` | Full ISO 8601 | `2026-04-08T14:30:52` |
| `%(app)s` | Foreground/source app name | `spotify` |
| `%(source)s` | Capture source description | `system` or `app:firefox` |
| `%(device)s` | Output device name | `alsa_output.pci-0000_00_1f.3.analog-stereo` |
| `%(duration)s` | Captured duration in seconds | `10` |
| `%(counter)d` | Auto-incrementing counter, per session | `1`, `2`, `3` |
| `%(label)s` | Optional label passed via IPC | `drum_fill` |
| `%(ext)s` | File extension | `wav` |

Numeric formatting follows printf conventions: `%(counter)05d` for zero-padding to 5 digits.

Default-value syntax: `%(label|untitled)s` falls back to `untitled` when the field is empty.

Filenames are sanitized to remove or replace characters that are illegal on common filesystems. Directory separators in the template are preserved; intermediate directories are created on demand.

The parser and sanitizer should be lifted (or directly ported) from `yt_dlp/utils/_utils.py`. The Unlicense license makes this trivial.

## 6. Per-app capture details

The per-app capture story differs significantly between backends, and is the most fiddly part of the project.

**PulseAudio:**

1. List sink-inputs via `pulsectl`
2. User selects one (or names a binary, e.g. `firefox`)
3. Create a null sink: `pactl load-module module-null-sink sink_name=echobuf_capture`
4. Move the target sink-input to that sink: `pactl move-sink-input <id> echobuf_capture`
5. Record from `echobuf_capture.monitor`
6. On source change or shutdown, restore original routing and unload the module

**Caveat:** moving a sink-input means the user no longer hears the audio through their normal output. To preserve hearing, also create a `module-loopback` from the null sink back to the original sink. This adds latency (typically 20–50ms) and is a tradeoff worth surfacing in the UI.

**PipeWire:**

PipeWire's graph model is cleaner. Create a virtual sink node, link the target stream's output ports to both the original sink and the capture node. No loopback needed; the user keeps hearing audio at full quality. This is the killer feature of the PipeWire backend.

For v1, ship system-wide capture as the default and per-app as an advanced opt-in. Per-app is where most of the bug reports will come from.

## 7. CLI

```
echobuf daemon                    # run the daemon in foreground
echobuf save [--label NAME]       # trigger a save via IPC
echobuf status                    # print daemon status
echobuf sources                   # list available capture sources
echobuf set-source <spec>         # change active source
echobuf pause / resume
echobuf quit                      # stop the daemon
```

The `daemon` command is what systemd invokes. All other commands are thin IPC clients.

## 8. File format

WAV only for v1. 16-bit PCM by default, configurable to 24-bit or float32. Sample rate matches the capture rate (no resampling). Channels match capture (typically stereo).

Rationale: WAV is universally supported by every DAW, sampler, and audio editor. No metadata complexity, no codec dependencies, no licensing concerns. FLAC and Opus are easy to add later via `soundfile`.

## 9. Dependencies

**Required:**
- Python 3.11+
- `numpy` — buffer storage
- `soundfile` — WAV writing (libsndfile binding)
- `pulsectl` — PulseAudio control (also works with pipewire-pulse)

**Optional / backend-specific:**
- `pipewire-python` — native PipeWire backend (if mature)
- `pystray` + `Pillow` — tray icon
- `python-xlib` or `pynput` — X11 hotkeys
- `tomli` (stdlib `tomllib` on 3.11+) — config parsing

**System:**
- `pw-record` / `parec` as fallback capture mechanism
- `libnotify` for notifications

## 10. Open questions

- Whether to ship the PipeWire-native backend in v1 or start with PulseAudio-only and add native PipeWire in v1.1. PulseAudio-only is simpler and works fine on PipeWire systems via `pipewire-pulse`; the only thing it gives up is the cleaner per-app capture story.
- Whether to detect silence at the head/tail of the saved buffer and trim it automatically, or leave that to the user.
- Whether to support multiple concurrent buffers (e.g., one for system, one for a specific app) or keep it strictly one buffer at a time.
- How to handle sample rate changes mid-capture (e.g., user switches output device). Cleanest answer is probably to drain and reopen the buffer at the new rate, accepting a brief gap.
- Whether the tray icon should bundle a tiny waveform preview of the most recent save.

## 11. Milestones

**v0.1 — walking skeleton**
- PulseAudio backend, system capture only
- Ring buffer + manual CLI save trigger
- Hardcoded output path
- No tray, no service

**v0.2 — usable**
- Config file
- Output template parser (port from yt-dlp)
- IPC socket + CLI client commands
- systemd unit

**v0.3 — daily-driver**
- Tray icon
- libnotify integration
- Per-app capture (PulseAudio)
- Documented WM/DE binding recipes (i3, sway, GNOME, KDE)

**v0.4 — polish**
- Native PipeWire backend
- Clean per-app capture via graph linking
- Source switching from the tray
- Pause/resume
- Optional in-process hotkey grab via `pynput` (for users who don't bind through their WM)

**v1.0**
- Documentation, packaging (PyPI + AUR), test coverage
- Probably an icon that isn't programmer art
