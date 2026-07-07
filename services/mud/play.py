"""play.py — a tiny, zero-dependency client for the Pac's Arcade MUD. 💜

    python services/mud/play.py            # connects to 127.0.0.1:4000
    python services/mud/play.py host port  # custom target

Works on Windows / macOS / Linux with just the Python 3 stdlib. If you'd rather, any
telnet or MUD client works too:  telnet 127.0.0.1 4000
Type your commands and press Enter. Type 'quit' to leave.
"""

from __future__ import annotations

import os
import socket
import sys
import threading


def _enable_ansi_on_windows() -> None:
    """Turn on ANSI colour processing in the Windows console (no-op elsewhere)."""
    # Force UTF-8 stdout so box-drawing/emoji don't crash the Windows console.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING | ...
    except Exception:
        pass


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
    _enable_ansi_on_windows()

    try:
        sock = socket.create_connection((host, port), timeout=10)
    except OSError as e:
        print(f"Couldn't reach the arcade at {host}:{port} — is the MUD running?  ({e})")
        print("Start it with:  python services/mud/server.py")
        return
    # IMPORTANT: create_connection's 10s timeout is for CONNECTING only. Clear it now, or the
    # socket keeps a 10s read timeout and drops you while you're reading (not typing). No kick.
    sock.settimeout(None)

    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                data = sock.recv(4096)
            except OSError:
                break
            if not data:
                break
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()
        stop.set()
        print("\r\n-- disconnected from the arcade. GG, fren. --\r\n")
        # The main thread is blocked on stdin.readline(); exit hard so the terminal returns to the
        # shell cleanly (no lingering session, no stuck command history on the up-arrow).
        os._exit(0)

    threading.Thread(target=reader, daemon=True).start()

    try:
        while not stop.is_set():
            line = sys.stdin.readline()
            if not line:
                break
            try:
                sock.sendall(line.encode("utf-8"))
            except OSError:
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop.set()
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
