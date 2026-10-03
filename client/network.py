import socket
import time
from shared.protocol import encode, Protocol


class Network:
    def __init__(self, host: str = "127.0.0.1", port: int = 5555):
        self.host = host
        self.port = port
        self.proto = Protocol()
        self.sock = None
        self.connected = False
        self.last_connect_attempt = 0
        self.connect()

    def connect(self):
        now = time.time()
        # Limit reconnection attempts to once every 2 seconds
        if now - self.last_connect_attempt < 2 and self.connected:
            return
        self.last_connect_attempt = now

        try:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass

            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setblocking(False)
            try:
                self.sock.connect((self.host, int(self.port)))
            except BlockingIOError:
                # connection in progress for non-blocking socket
                pass
            self.connected = True
        except Exception:
            # connection failed; will retry later
            self.connected = False

    def send(self, data: bytes):
        if not self.connected or not self.sock:
            self.connect()
            return False
        try:
            self.sock.send(data)
            return True
        except (BlockingIOError, BrokenPipeError, OSError):
            # Try reconnect next tick
            self.connected = False
            return False

    def send_move(self, dx, dy):
        payload = encode({"type": "move", "dx": dx, "dy": dy})
        self.send(payload)

    def receive(self):
        messages = []
        if not self.connected or not self.sock:
            self.connect()
            return messages

        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    # remote closed
                    self.connected = False
                    break
                messages.extend(self.proto.receive(data))
        except BlockingIOError:
            pass
        except (ConnectionResetError, OSError):
            self.connected = False

        return messages

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.connected = False
