from __future__ import annotations

import argparse
import json
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional


stop_event = threading.Event()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "TCP test stub for the IEC 61850 launcher. "
            "This executable binds to the requested IP and port, reads the values JSON, "
            "and keeps the process alive for start/stop testing."
        )
    )
    parser.add_argument("--ied-name", required=True)
    parser.add_argument("--type", required=True)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--values", required=True)
    return parser.parse_args()


def on_signal(_signum: int, _frame: object) -> None:
    stop_event.set()


def resolve_values_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def load_values(values_path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(values_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"values file missing: {values_path}", flush=True)
    except json.JSONDecodeError as exc:
        print(f"invalid JSON in values file: {exc}", flush=True)
    except OSError as exc:
        print(f"failed to read values file: {exc}", flush=True)
    return None


def accept_loop(listener: socket.socket) -> None:
    listener.settimeout(0.5)
    while not stop_event.is_set():
        try:
            connection, address = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            if stop_event.is_set():
                return
            raise

        with connection:
            print(f"client connected from {address[0]}:{address[1]}", flush=True)
            try:
                connection.settimeout(1.0)
                connection.recv(4096)
            except socket.timeout:
                pass
            except OSError:
                pass


def main() -> int:
    args = parse_args()
    values_path = resolve_values_path(args.values)

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    print(
        (
            f"starting test stub for {args.ied_name} ({args.type}) on "
            f"{args.bind}:{args.port} using {values_path}"
        ),
        flush=True,
    )
    print(
        "note: this executable is a TCP bind/process test stub, not a real IEC 61850 MMS server",
        flush=True,
    )

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        listener.bind((args.bind, args.port))
        listener.listen(5)
    except OSError as exc:
        print(f"bind/listen failed: {exc}", flush=True)
        listener.close()
        return 1

    thread = threading.Thread(target=accept_loop, args=(listener,), daemon=True)
    thread.start()

    last_updated_ms: Optional[int] = None
    last_error_at: float = 0.0

    try:
        while not stop_event.is_set():
            payload = load_values(values_path)
            if payload is None:
                now = time.monotonic()
                if now - last_error_at >= 1.0:
                    last_error_at = now
                time.sleep(0.1)
                continue

            updated_ms = payload.get("updated_unix_ms")
            if updated_ms != last_updated_ms:
                analog_count = len(payload.get("analogs", {}))
                bool_count = len(payload.get("bools", {}))
                word_count = len(payload.get("words", {}))
                print(
                    (
                        f"loaded values update {updated_ms}: "
                        f"analogs={analog_count}, bools={bool_count}, words={word_count}"
                    ),
                    flush=True,
                )
                last_updated_ms = updated_ms

            time.sleep(0.1)
    finally:
        stop_event.set()
        listener.close()
        thread.join(timeout=1.0)
        print("stub stopped", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())