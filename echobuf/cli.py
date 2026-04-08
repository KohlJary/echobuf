"""echobuf CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="echobuf", description="Audio instant-replay buffer")
    parser.add_argument("--config", type=str, default=None, help="Path to config file")
    sub = parser.add_subparsers(dest="command")

    # daemon
    sub.add_parser("daemon", help="Run the capture daemon in foreground")

    # save
    save_p = sub.add_parser("save", help="Trigger a save via IPC")
    save_p.add_argument("--label", type=str, default=None, help="Optional label for the file")

    # status
    sub.add_parser("status", help="Print daemon status")

    # sources
    sub.add_parser("sources", help="List available capture sources")

    # set-source
    set_src_p = sub.add_parser("set-source", help="Change active capture source")
    set_src_p.add_argument("source", help="Source spec: 'system' or 'app:<name>'")

    # pause / resume
    sub.add_parser("pause", help="Pause capture (keep daemon running)")
    sub.add_parser("resume", help="Resume capture")

    # quit
    sub.add_parser("quit", help="Stop the daemon")

    # tray
    sub.add_parser("tray", help="Run the system tray icon")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "daemon": _run_daemon,
        "save": _cmd_save,
        "status": _cmd_status,
        "sources": _cmd_sources,
        "set-source": _cmd_set_source,
        "pause": _cmd_pause,
        "resume": _cmd_resume,
        "quit": _cmd_quit,
        "tray": _cmd_tray,
    }
    commands[args.command](args)


def _run_daemon(args: argparse.Namespace) -> None:
    from .config import load_config
    from .daemon import Daemon

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    # Set up logging
    log_path = config.logging.file_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(log_path)),
        ],
    )

    daemon = Daemon(config)
    daemon.start()


def _ipc_command(msg: dict) -> dict:
    """Send an IPC command, handling connection errors."""
    from .ipc import ipc_send

    try:
        return ipc_send(msg)
    except ConnectionError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def _cmd_save(args: argparse.Namespace) -> None:
    msg: dict = {"cmd": "save"}
    if args.label:
        msg["label"] = args.label
    resp = _ipc_command(msg)
    if resp.get("ok"):
        print(f"Saved: {resp['path']}")
    else:
        print(f"Save failed: {resp.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def _cmd_status(args: argparse.Namespace) -> None:
    resp = _ipc_command({"cmd": "status"})
    if resp.get("ok"):
        state = "paused" if resp.get("paused") else "recording"
        print(f"echobuf daemon is running ({state})")
        print(f"  Backend: {resp.get('backend', 'unknown')}")
        print(f"  Source: {resp.get('source', 'system')}")
        print(f"  Buffer: {resp['buffered']}s / {resp['buffer_seconds']}s")
        print(f"  Format: {resp['sample_rate']}Hz, {resp['channels']}ch")
        print(f"  Saves this session: {resp['saves']}")
    else:
        print("Status check failed", file=sys.stderr)
        sys.exit(1)


def _cmd_sources(args: argparse.Namespace) -> None:
    resp = _ipc_command({"cmd": "list_sources"})
    if resp.get("ok"):
        for src in resp["sources"]:
            binary = f" ({src['binary']})" if src.get("binary") else ""
            print(f"  [{src['type']}] {src['name']}{binary}")
    else:
        print("Failed to list sources", file=sys.stderr)
        sys.exit(1)


def _cmd_set_source(args: argparse.Namespace) -> None:
    spec = args.source
    if spec == "system":
        msg = {"cmd": "set_source", "type": "system"}
    elif spec.startswith("app:"):
        msg = {"cmd": "set_source", "type": "app", "name": spec[4:]}
    else:
        print(f"Invalid source spec: {spec!r} (use 'system' or 'app:<name>')", file=sys.stderr)
        sys.exit(1)
    resp = _ipc_command(msg)
    if resp.get("ok"):
        print(f"Source changed to: {resp['source']}")
    else:
        print(f"Failed: {resp.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def _cmd_pause(args: argparse.Namespace) -> None:
    resp = _ipc_command({"cmd": "pause"})
    if resp.get("ok"):
        print("Capture paused")
    else:
        print(f"Pause failed: {resp.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def _cmd_resume(args: argparse.Namespace) -> None:
    resp = _ipc_command({"cmd": "resume"})
    if resp.get("ok"):
        print("Capture resumed")
    else:
        print(f"Resume failed: {resp.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def _cmd_quit(args: argparse.Namespace) -> None:
    resp = _ipc_command({"cmd": "quit"})
    if resp.get("ok"):
        print("Daemon stopping")
    else:
        print(f"Quit failed: {resp.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def _cmd_tray(args: argparse.Namespace) -> None:
    from .tray import run_tray
    run_tray()
