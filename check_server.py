"""Self-check of the dedicated server - does it really work without pygame?

The server is its own package since b12: it must start on a bare Python, with
no pygame, no display and no libraries beyond the standard set. This script
proves it on your machine:

    python check_server.py                  # start, handshake, stop
    python check_server.py --forbid-pygame  # same, but pygame is poisoned first
    python check_server.py --port 25565     # use a fixed port

Exit code 0 means the server is fine.
"""

import argparse
import builtins
import json
import socket
import struct
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def forbid_pygame():
    """Make `import pygame` fail - the server must not need it at all."""
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "pygame" or name.startswith("pygame."):
            raise ImportError("pygame is not allowed on the server (b12 split)")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = guarded


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def encode(message: dict) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


class Talker:
    """A tiny protocol client: the same framing the real game uses."""

    def __init__(self, port, timeout=3.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.sock.settimeout(0.2)
        self.buffer = b""
        self.inbox = []

    def send(self, message):
        self.sock.sendall(encode(message))

    def poll(self, seconds=0.6):
        end = time.time() + seconds
        while time.time() < end:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            self.buffer += data
            while len(self.buffer) >= 4:
                length = struct.unpack("!I", self.buffer[:4])[0]
                if len(self.buffer) < 4 + length:
                    break
                chunk, self.buffer = self.buffer[4:4 + length], self.buffer[4 + length:]
                try:
                    self.inbox.append(json.loads(chunk))
                except ValueError:
                    pass
        return self.inbox

    def wait_for(self, kind, seconds=5.0):
        end = time.time() + seconds
        while time.time() < end:
            for message in self.inbox:
                if message.get("type") == kind:
                    return message
            self.poll(0.2)
        return None

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    parser.add_argument("--forbid-pygame", action="store_true",
                        help="fail if the server tries to import pygame")
    parser.add_argument("--seconds", type=float, default=8.0,
                        help="how long to wait for the handshake")
    args = parser.parse_args(argv)

    if args.forbid_pygame:
        forbid_pygame()
        print("pygame import is now forbidden - good, that is the point")

    print(f"python {sys.version.split()[0]} on {sys.platform}")
    print(f"project folder: {ROOT}")

    try:
        from server import server as server_module
    except ImportError as exc:
        print(f"FAIL: the server code did not import: {exc}")
        return 1

    port = args.port or free_port()
    game_server = server_module.GameServer(host=args.host, port=port, accounts_path=None,
                                           config={**server_module.DEFAULT_CONFIG,
                                                   "animals": False, "wolves": False,
                                                   "tasks": False, "hunger_rate": 0})
    thread = threading.Thread(target=game_server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with socket.create_connection((args.host, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.15)
    else:
        print("FAIL: the server did not start listening")
        return 1
    print(f"server is listening on {args.host}:{port}")

    talker = Talker(port)
    talker.send({"type": "guest", "name": "SelfCheck"})
    welcome = talker.wait_for("welcome", args.seconds)
    if welcome is None:
        print("FAIL: no welcome packet - the handshake did not finish")
        talker.close()
        return 1
    print(f"handshake ok: player id {welcome.get('id')!r}, "
          f"terrain {len(welcome.get('terrain', ''))} tiles, "
          f"build {welcome.get('build') or welcome.get('rules', {}).get('build', '?')}")

    talker.send({"type": "move", "dx": 4, "dy": 0})
    talker.poll(0.4)
    positions = [m for m in talker.inbox if m.get("type") == "state"]
    print(f"movement answered with {len(positions)} state packet(s)")
    talker.close()

    game_server.running = False
    time.sleep(0.3)
    print("OK: the server works" + (" without pygame" if args.forbid_pygame else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
