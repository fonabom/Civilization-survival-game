import unittest
import json
from shared.protocol import Protocol, encode

class TestProtocol(unittest.TestCase):
    def test_encode(self):
        proto = Protocol()
        data = {"hello": "world"}
        encoded = proto.encode(data)
        # Length of '{"hello": "world"}' is 18. Packed as !I (4 bytes) + 18 bytes = 22 bytes total.
        self.assertEqual(len(encoded), 22)
        self.assertEqual(encoded[:4], b'\x00\x00\x00\x12')

    def test_receive_complete(self):
        proto = Protocol()
        data = {"test": 123}
        encoded = proto.encode(data)
        msgs = proto.receive(encoded)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0], data)

    def test_receive_fragmented(self):
        proto = Protocol()
        data = {"id": 1}
        encoded = proto.encode(data)
        
        # Split into two chunks
        chunk1 = encoded[:2]
        chunk2 = encoded[2:]
        
        msgs1 = proto.receive(chunk1)
        self.assertEqual(len(msgs1), 0) # Incomplete
        
        msgs2 = proto.receive(chunk2)
        self.assertEqual(len(msgs2), 1) # Complete now
        self.assertEqual(msgs2[0], data)

    def test_receive_multiple_coalesced(self):
        proto = Protocol()
        data1 = {"a": 1}
        data2 = {"b": 2}
        encoded = proto.encode(data1) + proto.encode(data2)
        
        msgs = proto.receive(encoded)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0], data1)
        self.assertEqual(msgs[1], data2)

if __name__ == '__main__':
    unittest.main()
