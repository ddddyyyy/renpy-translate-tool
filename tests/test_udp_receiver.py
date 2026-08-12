import json
import socket
import unittest

from renpy_translate.core import parse_packet, receive_once


class UdpReceiverTest(unittest.TestCase):
    def test_local_udp_round_trip(self):
        event = {
            "protocol": 1,
            "event": "dialogue",
            "who": "Bree",
            "text": "Hello, world.",
        }

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.sendto(
                    json.dumps(event).encode("utf-8"), receiver.getsockname()
                )
            self.assertEqual(receive_once(receiver), event)

    def test_rejects_invalid_packet(self):
        with self.assertRaises(ValueError):
            parse_packet(b"[]")


if __name__ == "__main__":
    unittest.main()
