import json
import struct

class Protocol:
    def __init__(self):
        self.buffer = b""

    def encode(self, data: dict) -> bytes:
        """Encodes a dictionary into a length-prefixed bytes object."""
        json_data = json.dumps(data).encode("utf-8")
        length = len(json_data)
        return struct.pack("!I", length) + json_data

    def receive(self, data: bytes) -> list[dict]:
        """
        Appends new data to the buffer and yields all complete messages found.
        Returns a list of decoded dictionaries.
        """
        self.buffer += data
        messages = []

        while True:
            if len(self.buffer) < 4:
                break

            length = struct.unpack("!I", self.buffer[:4])[0]
            
            if len(self.buffer) < 4 + length:
                break

            message_data = self.buffer[4:4+length]
            self.buffer = self.buffer[4+length:]

            try:
                messages.append(json.loads(message_data.decode("utf-8")))
            except json.JSONDecodeError:
                print("Error decoding packet")
                
        return messages

# Helper instances for simple one-off encoding usually needed by the sender
_proto = Protocol()
def encode(data: dict) -> bytes:
    return _proto.encode(data)
