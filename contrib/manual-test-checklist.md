# echobuf Manual Test Checklist

Run through this to verify all functionality end-to-end. Play some audio (music, YouTube, etc.) before starting so there's something to capture.

## Prerequisites

- [ ] Audio is playing from at least one application
- [ ] No existing echobuf daemon running (`echobuf quit` or `pkill -f "echobuf daemon"`)

---

## 1. Daemon startup

```bash
echobuf daemon &
```

- [ ] Daemon starts without errors
- [ ] Logs show backend detected (pipewire or pulse)
- [ ] Logs show IPC listening on socket

## 2. Status

```bash
echobuf status
```

- [ ] Shows "recording"
- [ ] Shows correct backend (pipewire/pulse)
- [ ] Shows source as "system"
- [ ] Buffer fill is increasing (run twice a few seconds apart)
- [ ] Format shows expected sample rate and channels

## 3. Save (basic)

```bash
echobuf save
```

- [ ] Prints saved file path
- [ ] File exists at the printed path
- [ ] File is a valid WAV (play it back — you should hear what was playing)
- [ ] Desktop notification appears (if notify-send is installed)

## 4. Save (with label)

```bash
echobuf save --label "test_clip"
```

- [ ] File path contains "test_clip" in the filename
- [ ] File is a valid WAV

## 5. Pause / Resume

```bash
echobuf pause
echobuf status
```

- [ ] Status shows "paused"
- [ ] Buffer fill stops increasing

```bash
echobuf resume
echobuf status
```

- [ ] Status shows "recording"
- [ ] Buffer fill starts increasing again

## 6. Source listing

```bash
echobuf sources
```

- [ ] Lists "system" source
- [ ] Lists running audio apps (e.g., Firefox, Spotify) with binary names

## 7. Source switching

```bash
echobuf set-source app:<running_app_name>
echobuf status
```

- [ ] Status shows new source (e.g., "app:firefox")
- [ ] Save captures only that app's audio (play audio from another app simultaneously to verify isolation)

```bash
echobuf set-source system
```

- [ ] Switches back to system capture

## 8. Config file

```bash
cat ~/.config/echobuf/config.toml
```

- [ ] File exists (created by tray or manually)
- [ ] Editing `buffer.seconds` and restarting daemon applies the change
- [ ] Editing `output.directory` and restarting changes where files are saved
- [ ] Editing `output.template` and restarting changes filename format

## 9. Custom template

Set in config:
```toml
[output]
template = "%(date)s/%(app)s/%(label|untitled)s_%(counter)03d.%(ext)s"
```

Restart daemon, then:

```bash
echobuf save --label "riff"
```

- [ ] File is saved at `<output_dir>/<date>/<app>/riff_001.wav`
- [ ] Subsequent saves increment the counter (002, 003, etc.)

## 10. Tray icon

```bash
echobuf tray &
```

- [ ] Icon appears in system tray
- [ ] Right-click/click shows menu
- [ ] "Save now" triggers a save
- [ ] "Pause/Resume" toggles capture state
- [ ] "Open save folder" opens the output directory
- [ ] "Edit config" opens the config file in a text editor
- [ ] "Quit daemon" stops the daemon

## 11. Backend selection

Test forced PulseAudio backend:
```toml
[capture]
backend = "pulse"
```

- [ ] Daemon starts with pulse backend (check status or logs)
- [ ] Save produces valid audio

Reset to auto:
```toml
[capture]
backend = "auto"
```

- [ ] Daemon auto-detects (should pick pipewire if available)

## 12. Hotkey (optional, requires echobuf[hotkey])

Set in config:
```toml
[hotkey]
binding = "<ctrl>+<shift>+s"
```

Restart daemon, then press Ctrl+Shift+S:

- [ ] Save is triggered (check logs or notification)
- [ ] File is produced

## 13. systemd service

```bash
systemctl --user status echobuf
```

- [ ] Service is active and running
- [ ] `echobuf status` works against the systemd-managed daemon

```bash
systemctl --user restart echobuf
sleep 2
echobuf status
```

- [ ] Daemon comes back up cleanly after restart

## 14. Clean shutdown

```bash
echobuf quit
```

- [ ] Daemon exits cleanly (no orphan processes)
- [ ] Socket file removed (`ls $XDG_RUNTIME_DIR/echobuf.sock` should fail)
- [ ] If per-app capture was active, audio routing is restored

---

## Summary

| Area | Tests |
|------|-------|
| Daemon lifecycle | startup, shutdown, restart |
| Capture | system, per-app, pause/resume |
| Save | basic, labeled, template formatting |
| IPC/CLI | status, sources, set-source, quit |
| Config | loading, template, backend selection |
| Tray | menu items, daemon control |
| Hotkey | optional grab + trigger |
| systemd | enable, status, restart |
