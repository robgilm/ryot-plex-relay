import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import relay  # noqa: E402

BOUNDARY = "----------------------xyz"
PAYLOAD = {"event": "media.play", "Metadata": {"viewOffset": 1000, "duration": 2000}}


def plex_body(with_thumb):
    parts = (
        f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"payload\"\r\n"
        f"Content-Type: application/json\r\n\r\n{json.dumps(PAYLOAD)}\r\n"
    ).encode()
    if with_thumb:
        parts += (
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"thumb\"; filename=\"poster.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode() + b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x80\x81\xfe\r\n"
    return parts + f"--{BOUNDARY}--\r\n".encode()


class StripTests(unittest.TestCase):
    def test_thumb_is_removed_and_result_is_utf8(self):
        out = relay.strip_to_payload(plex_body(True), f"multipart/form-data; boundary={BOUNDARY}")
        text = out.decode("utf-8")  # raises if binary survived
        self.assertIn('"media.play"', text)
        self.assertNotIn("thumb", text)

    def test_payload_only_body_still_parses(self):
        out = relay.strip_to_payload(plex_body(False), f"multipart/form-data; boundary={BOUNDARY}")
        self.assertIn('"media.play"', out.decode("utf-8"))

    def test_json_body_passes_through(self):
        body = json.dumps(PAYLOAD).encode()
        self.assertEqual(relay.strip_to_payload(body, "application/json"), body)

    def test_event_name(self):
        self.assertEqual(relay.event_name(plex_body(True)), "media.play")


class EndToEnd(unittest.TestCase):
    def test_forwards_to_a_strict_utf8_server(self):
        seen = {}

        class FakeRyot(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                try:
                    seen["text"] = body.decode("utf-8")
                    code = 202
                except UnicodeDecodeError:
                    code = 400
                self.send_response(code)
                self.end_headers()

            def log_message(self, *a):
                pass

        ryot = HTTPServer(("127.0.0.1", 0), FakeRyot)
        threading.Thread(target=ryot.serve_forever, daemon=True).start()
        handler = relay.make_handler(f"http://127.0.0.1:{ryot.server_port}/_i/test", 5)
        proxy = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()

        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_port}/plex",
            data=plex_body(True),
            headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        )
        with urllib.request.urlopen(req) as reply:
            self.assertEqual(reply.status, 200)
        self.assertIn('"media.play"', seen["text"])
        ryot.shutdown()
        proxy.shutdown()


class ScrobbleRepeat(unittest.TestCase):
    def run_events(self, repeats, events):
        got = []

        class FakeRyot(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                got.append(relay.event_name(body))
                self.send_response(202)
                self.end_headers()

            def log_message(self, *a):
                pass

        ryot = HTTPServer(("127.0.0.1", 0), FakeRyot)
        threading.Thread(target=ryot.serve_forever, daemon=True).start()
        handler = relay.make_handler(f"http://127.0.0.1:{ryot.server_port}/_i/test", 5, repeats, 0)
        proxy = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        for event in events:
            body = json.dumps({"event": event}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{proxy.server_port}/plex", data=body, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req).close()
        ryot.shutdown()
        proxy.shutdown()
        return got

    def test_default_sends_every_event_once(self):
        self.assertEqual(self.run_events(1, ["media.play", "media.scrobble", "media.stop"]),
                         ["media.play", "media.scrobble", "media.stop"])

    def test_scrobble_is_repeated_and_other_events_are_not(self):
        self.assertEqual(self.run_events(2, ["media.play", "media.scrobble", "media.stop"]),
                         ["media.play", "media.scrobble", "media.scrobble", "media.stop"])


if __name__ == "__main__":
    unittest.main()
