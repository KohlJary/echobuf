"""echobuf CLI entry point."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="echobuf", description="Audio instant-replay buffer")
    sub = parser.add_subparsers(dest="command")

    # daemon
    daemon_p = sub.add_parser("daemon", help="Run the capture daemon in foreground")
    daemon_p.add_argument("--buffer", type=float, default=10.0, help="Buffer length in seconds")
    daemon_p.add_argument("--rate", type=int, default=48000, help="Sample rate")
    daemon_p.add_argument("--channels", type=int, default=2, help="Channel count")
    daemon_p.add_argument("--output", type=str, default=None, help="Output directory")

    # save
    save_p = sub.add_parser("save", help="Trigger a save (sends SIGUSR1 to the daemon)")
    save_p.add_argument("--label", type=str, default=None, help="Optional label for the file")

    # status
    sub.add_parser("status", help="Check if the daemon is running")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "daemon":
        _run_daemon(args)
    elif args.command == "save":
        _trigger_save(args)
    elif args.command == "status":
        _check_status()


def _run_daemon(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    from .daemon import Daemon

    output_dir = Path(args.output) if args.output else None
    kwargs = {
        "buffer_seconds": args.buffer,
        "sample_rate": args.rate,
        "channels": args.channels,
    }
    if output_dir:
        kwargs["output_dir"] = output_dir

    daemon = Daemon(**kwargs)
    daemon.start()


def _trigger_save(args: argparse.Namespace) -> None:
    from .daemon import _pid_path

    pid_path = _pid_path()
    if not pid_path.exists():
        print("echobuf daemon is not running", file=sys.stderr)
        sys.exit(1)

    pid = int(pid_path.read_text().strip())

    try:
        os.kill(pid, signal.SIGUSR1)
        print(f"Save triggered (sent SIGUSR1 to pid {pid})")
    except ProcessLookupError:
        print("echobuf daemon is not running (stale PID file)", file=sys.stderr)
        pid_path.unlink(missing_ok=True)
        sys.exit(1)
    except PermissionError:
        print(f"Permission denied sending signal to pid {pid}", file=sys.stderr)
        sys.exit(1)


def _check_status() -> None:
    from .daemon import _pid_path

    pid_path = _pid_path()
    if not pid_path.exists():
        print("echobuf daemon is not running")
        sys.exit(1)

    pid = int(pid_path.read_text().strip())
    try:
        os.kill(pid, 0)  # Check if process exists
        print(f"echobuf daemon is running (pid {pid})")
    except ProcessLookupError:
        print("echobuf daemon is not running (stale PID file)")
        pid_path.unlink(missing_ok=True)
        sys.exit(1)
