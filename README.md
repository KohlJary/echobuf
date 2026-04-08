# echobuf

Audio instant-replay buffer for Linux. Continuously records system audio into a rolling RAM buffer — hit a hotkey and the last N seconds are saved to a WAV file. Like ShadowPlay, but for audio.

## Install

```bash
pip install echobuf
```

Requires Python 3.11+ and either PipeWire or PulseAudio.

Optional extras:

```bash
pip install echobuf[tray]      # system tray icon
pip install echobuf[hotkey]    # built-in global hotkey via pynput
pip install echobuf[dev]       # pytest for development
```

## Quick start

```bash
# Start the daemon
echobuf daemon &

# Save the last 10 seconds of audio
echobuf save

# Save with a label
echobuf save --label "cool_riff"

# Check status
echobuf status

# Stop the daemon
echobuf quit
```

Saved files go to `~/samples/` by default, organized by date.

## Binding to your WM

The recommended way to trigger saves is by binding `echobuf save` in your window manager. The daemon doesn't need to know about input devices — your WM handles that better than we can.

**i3 / sway:**

```
bindsym $mod+Shift+s exec --no-startup-id echobuf save
bindsym $mod+Shift+d exec --no-startup-id echobuf save --label dialogue
bindsym $mod+Shift+m exec --no-startup-id echobuf save --label "$(rofi -dmenu -p tag)"
```

**GNOME:** Settings → Keyboard → Custom Shortcuts → add `echobuf save`

**KDE:** System Settings → Shortcuts → Custom Shortcuts → add `echobuf save`

## Configuration

Config lives at `~/.config/echobuf/config.toml`. Created with defaults on first use via the tray icon, or create it manually:

```toml
[buffer]
seconds = 10              # rolling buffer length
post_seconds = 0          # extra seconds captured after save

[capture]
backend = "auto"          # auto | pipewire | pulse
source = "system"         # system | app:<name>
sample_rate = 48000
channels = 2

[output]
directory = "~/samples"
template = "%(date)s/%(time)s_%(counter)03d.%(ext)s"
format = "wav"
sanitize = true

[hotkey]
binding = ""              # e.g. "<ctrl>+<shift>+s" (requires echobuf[hotkey])

[notifications]
enabled = true
sound = true

[logging]
level = "info"
```

## Output templates

File paths use yt-dlp–style tokens:

| Token | Example | Description |
|-------|---------|-------------|
| `%(date)s` | `2026-04-08` | Local date |
| `%(time)s` | `143052` | Local time (HHMMSS) |
| `%(timestamp)s` | `1744128652` | Unix epoch |
| `%(iso)s` | `2026-04-08T14:30:52` | Full ISO 8601 |
| `%(app)s` | `spotify` | Source app name |
| `%(source)s` | `system` | Capture source |
| `%(device)s` | `default` | Output device |
| `%(duration)d` | `10` | Captured seconds |
| `%(counter)03d` | `001` | Auto-incrementing counter |
| `%(label)s` | `drum_fill` | Label from `--label` flag |
| `%(ext)s` | `wav` | File extension |

Default values: `%(label|untitled)s` falls back to `untitled` when no label is given.

## CLI reference

```
echobuf daemon              Run the capture daemon in foreground
echobuf save [--label NAME] Trigger a save
echobuf status              Print daemon status (backend, buffer, saves)
echobuf sources             List available capture sources (system + apps)
echobuf set-source <spec>   Switch source: "system" or "app:<name>"
echobuf pause               Pause capture (daemon keeps running)
echobuf resume              Resume capture
echobuf quit                Stop the daemon
echobuf tray                Launch the system tray icon
```

## Per-app capture

Capture audio from a specific application instead of the full system mix:

```bash
# Via config
[capture]
source = "app:firefox"

# At runtime
echobuf set-source app:spotify
echobuf set-source system          # switch back
```

On **PipeWire**, per-app capture uses native graph linking — the app's audio is tapped without any routing changes, so there's no latency penalty and the user keeps hearing audio normally.

On **PulseAudio**, a null sink + loopback is created. The user still hears audio, but through a loopback with ~30ms latency.

## System tray

```bash
echobuf tray
```

Requires `echobuf[tray]`. Provides a menu to save, pause/resume, open the save folder, edit config, and quit the daemon.

## systemd service

A unit file is included at `contrib/echobuf.service`. To install:

```bash
cp contrib/echobuf.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now echobuf
```

The tray icon should be started separately via your desktop environment's autostart.

## Architecture

```
┌──────────────────────────────────────────────┐
│                echobuf daemon                │
│                                              │
│  Audio Source ──▶ Ring Buffer ──▶ WAV Writer  │
│  (parec/pw-record)  (numpy)    (on trigger)  │
│                                              │
│  IPC Server (Unix socket, JSON)              │
└──────────┬───────────────────────────────────┘
           │
    CLI / Tray / WM binding
```

- **Ring buffer**: preallocated NumPy array, ~22 MB for 60s of 48kHz stereo
- **Backends**: PipeWire (pw-record) auto-detected, PulseAudio (parec) fallback
- **IPC**: Unix socket at `$XDG_RUNTIME_DIR/echobuf.sock`, line-delimited JSON
- **Output**: 16-bit PCM WAV via libsndfile

## License

MIT
