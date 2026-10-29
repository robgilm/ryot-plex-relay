"""Forwards Plex webhooks to Ryot's Plex Sink without the poster image.

Plex sends every webhook as multipart/form-data with a JSON `payload` part and,
on media.play events, a binary `thumb` image part. Ryot reads the request body
as UTF-8 text, so it answers 400 to any event that carries the image. This relay
keeps only the `payload` part and forwards it to Ryot unchanged otherwise.
"""
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CRLF = b"\r\n"
PAYLOAD = re.compile(rb'name="payload"[^\r]*\r\n(?:Content-Type:[^\r]*\r\n)?\r\n(\{.*?\})\r\n--', re.S)
EVENT = re.compile(rb'"event"\s*:\s*"([^"]+)"')


def strip_to_payload(body, content_type):
    """Returns the request body reduced to the `payload` part; anything else passes through."""
    payload = PAYLOAD.search(body)
    boundary = re.search(r"boundary=([^;]+)", content_type or "")
    if not (payload and boundary):
        return body
    b = boundary.group(1).strip('"').encode()
    head = (
        b"--" + b + CRLF
        + b'Content-Disposition: form-data; name="payload"' + CRLF
        + b"Content-Type: application/json" + CRLF + CRLF
    )
    return head + payload.group(1) + CRLF + b"--" + b + b"--" + CRLF


def event_name(body):
    found = EVENT.search(body)
    return found.group(1).decode("utf8", "replace") if found else "unknown"


def make_handler(forward_url, timeout, scrobble_repeats=1, repeat_delay=0.2):
    def forward(out, content_type):
        request = urllib.request.Request(
            forward_url, data=out, method="POST", headers={"Content-Type": content_type}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                return reply.status
        except urllib.error.HTTPError as err:
            return err.code
        except Exception as err:
            return type(err).__name__

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            out = strip_to_payload(body, content_type)
            event = event_name(out)
            # In my tests Ryot only completed a watch when it received media.scrobble twice.
            sends = scrobble_repeats if event == "media.scrobble" else 1
            for i in range(sends):
                if i:
                    time.sleep(repeat_delay)
                status = forward(out, content_type)
                # The forward URL contains Ryot's webhook id, so it is never logged.
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {event} -> Ryot {status}", flush=True)
            # Plex does not retry, so it always gets a quick 200.
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    return Handler


def main():
    forward_url = os.environ.get("FORWARD_URL", "").strip()
    if not forward_url:
        sys.exit("FORWARD_URL is required: the Plex Sink URL shown in Ryot (…/_i/<id>)")
    port = int(os.environ.get("LISTEN_PORT", "8080"))
    timeout = float(os.environ.get("FORWARD_TIMEOUT", "15"))
    scrobble_repeats = max(1, int(os.environ.get("SCROBBLE_REPEATS", "1")))
    print(f"Listening on :{port}", flush=True)
    handler = make_handler(forward_url, timeout, scrobble_repeats)
    ThreadingHTTPServer(("0.0.0.0", port), handler).serve_forever()


if __name__ == "__main__":
    main()
