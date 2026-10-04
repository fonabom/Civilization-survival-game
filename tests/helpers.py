"""Shared test helpers: a raw protocol client with the auth handshake."""

import json
import socket
import struct
import time


def encode(message: dict) -> bytes:
    payload = json.dumps(message).encode()
    return struct.pack("!I", len(payload)) + payload


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class RawClient:
    """Minimal protocol client: connect -> auth -> talk."""

    def __init__(self, port, timeout=3.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.sock.settimeout(0.2)
        self.buffer = b""
        self.inbox = []

    def send(self, message):
        self.sock.sendall(encode(message))

    def poll(self, seconds=0.5):
        end = time.time() + seconds
        while time.time() < end:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                self.inbox.append({"__type__": "DISCONNECTED"})
                break
            if not data:
                self.inbox.append({"__type__": "DISCONNECTED"})
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
                    self.inbox.append({"__type__": "BAD_JSON"})
        return self.inbox

    def auth(self, name="Tester", kind="guest", password="secret123"):
        """Handshake; returns the welcome packet (or None)."""
        self.poll(0.3)
        if kind == "guest":
            self.send({"type": "guest", "name": name})
        else:
            self.send({"type": kind, "username": name, "password": password})
        self.poll(0.7)
        for message in self.inbox:
            if message.get("type") == "welcome":
                return message
        return None

    def notifications(self, seconds=0.5):
        return [m for m in self.poll(seconds) if m.get("type") == "notification"]

    def notif_keys(self, seconds=0.5):
        return [m.get("key") for m in self.notifications(seconds)]

    def of_type(self, mtype, seconds=0.5):
        return [m for m in self.poll(seconds) if m.get("type") == mtype]

    def clear(self):
        self.inbox.clear()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
