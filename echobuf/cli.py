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

    # quit
    sub.add_parser("quit", help="Stop the daemon")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "daemon": _run_daemon,
        "save": _cmd_save,
        "status": _cmd_status,
        "sources": _cmd_sources,
        "quit": _cmd_quit,
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
        print(f"echobuf daemon is running")
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
            print(f"  [{src['type']}] {src['name']}")
    else:
        print("Failed to list sources", file=sys.stderr)
        sys.exit(1)


def _cmd_quit(args: argparse.Namespace) -> None:
    resp = _ipc_command({"cmd": "quit"})
    if resp.get("ok"):
        print("Daemon stopping")
    else:
        print(f"Quit failed: {resp.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)
