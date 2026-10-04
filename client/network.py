"""Networking layer for the client.

The socket lives in background threads:
  * `_connect_loop` (re)connects and reports the connection state;
  * `_reader_loop` reads, frames and queues incoming messages.

The game loop only calls `receive()` and `send_dict()`, so a dead connection can
never crash the client with `AttributeError: 'NoneType' object has no attribute
'send'` (which is what happened when menus wrote to `net.sock` directly).

`auth` is the payload sent as soon as a connection is established: either
`{"type": "login"|"register"|"guest", ...}`. The server answers with
`auth_ok` / `auth_error`.
"""

import queue
import socket
import threading
import time

from shared.protocol import Protocol, encode

CONNECT_TIMEOUT = 4.0
RECONNECT_DELAY = 2.0


class Network:
    def __init__(self, host: str = "127.0.0.1", port: int = 5555,
                 name: str = "Player", auth: dict = None):
        self.host = host
        self.port = int(port)
        self.name = name
        self.auth = auth or {"type": "guest", "name": name}
        self.proto = Protocol()
        self.sock = None
        self.connected = False
        self.status = "Connecting..."      # shown in the HUD
        self.last_error = None
        self.messages = queue.Queue()

        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._sock_lock = threading.Lock()

        threading.Thread(target=self._connect_loop, name="net-connect", daemon=True).start()

    # ------------------------------------------------------------- connection
    def _connect_loop(self):
        while not self._stop.is_set():
            if self.connected:
                time.sleep(0.2)
                continue
            try:
                self.status = f"Connecting to {self.host}:{self.port}..."
                sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT)
                sock.settimeout(1.0)
                with self._sock_lock:
                    self.sock = sock
                self.proto = Protocol()          # fresh framing buffer
                self.connected = True
                self.last_error = None
                self.status = "Connected"
                threading.Thread(target=self._reader_loop, args=(sock,),
                                 name="net-reader", daemon=True).start()
                self.send_dict(self.auth)        # log in / register / join as guest
            except OSError as exc:
                self.last_error = str(exc)
                self.status = f"Offline ({exc})"
                self.connected = False
                time.sleep(RECONNECT_DELAY)

    def _reader_loop(self, sock):
        try:
            while not self._stop.is_set():
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    continue
                except (ConnectionResetError, ConnectionAbortedError, OSError) as exc:
                    self.last_error = str(exc)
                    break
                if not data:
                    self.last_error = "Server closed the connection"
                    break
                for message in self.proto.receive(data):
                    self.messages.put(message)
        finally:
            with self._sock_lock:
                if self.sock is sock:
                    self.sock = None
            try:
                sock.close()
            except OSError:
                pass
            self.connected = False
            self.status = "Disconnected - reconnecting..."

    # ------------------------------------------------------------------ output
    def send_dict(self, message: dict) -> bool:
        """Send a message; returns False instead of raising when offline."""
        with self._send_lock:
            sock = self.sock
            if sock is None:
                return False
            try:
                sock.sendall(encode(message))
                return True
            except OSError as exc:
                self.last_error = str(exc)
                self.connected = False
                return False

    def send(self, data: bytes) -> bool:
        with self._send_lock:
            sock = self.sock
            if sock is None:
                return False
            try:
                sock.sendall(data)
                return True
            except OSError as exc:
                self.last_error = str(exc)
                self.connected = False
                return False

    def send_move(self, dx: float, dy: float) -> bool:
        return self.send_dict({"type": "move", "dx": dx, "dy": dy})

    def set_auth(self, auth: dict):
        self.auth = auth

    # ------------------------------------------------------------------- input
    def receive(self) -> list:
        out = []
        while True:
            try:
                out.append(self.messages.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        self._stop.set()
        with self._sock_lock:
            sock, self.sock = self.sock, None
        self.connected = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
