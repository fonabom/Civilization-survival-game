import socket
from shared.protocol import encode, Protocol

class Network:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(False) # Non-blocking mode
        try:
            self.sock.connect(("127.0.0.1", 5555))
        except BlockingIOError:
            pass # Connection in progress
        self.proto = Protocol()

    def send_move(self, dx, dy):
        try:
            self.sock.send(encode({
                "type": "move",
                "dx": dx,
                "dy": dy
            }))
        except BlockingIOError:
            pass # Buffer full, ignore or retry later for movement
        
    def receive(self):
        """Reads all available messages from the socket (non-blocking)."""
        messages = []
        try:
            while True:
                data = self.sock.recv(4096)
                if not data: 
                    # Disconnection logic could go here
                    break
                messages.extend(self.proto.receive(data))
        except BlockingIOError:
            pass # No more data
        
        return messages
