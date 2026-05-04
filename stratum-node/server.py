#!/usr/bin/env python3
"""
miner-server: HTTP service for simple-miner-dash running on the stratum node.

Listens on localhost only — never bind to a public interface.
Tor handles all external access via a hidden service pointed at this port.

Configuration: edit the constants below before deploying.
"""

import http.server
import json
import os
import re
import sys
import urllib.parse

# ── Configuration ─────────────────────────────────────────────────────────────
# Port to listen on (must match HiddenServicePort target in torrc.snippet)
PORT = 5000

# Path to ckpool user log directory.
# For ckpool-solo:      /var/log/ckpool-solo/users
# For ckpool-solo-lhr:  /var/log/ckpool-solo-lhr/users
USERS_DIR = "/var/log/ckpool-solo/users"

# Strict Bitcoin address regex: bech32 (bc1...) and legacy (1... / 3...)
# Excludes path separators and all other filesystem-special characters.
ADDRESS_RE = re.compile(r'^(bc1[a-z0-9]{25,90}|[13][a-zA-Z0-9]{25,34})$')
# ─────────────────────────────────────────────────────────────────────────────


class MinerHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler — only responds to GET /?address=<addr>."""

    # Silence the default per-request log line (keeps systemd journal clean)
    def log_message(self, fmt, *args):
        pass

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            address_list = params.get("address", [])

            if not address_list:
                self.send_json(400, {"error": "invalid_address"})
                return

            address = address_list[0].strip()

            # Validate address format
            if not ADDRESS_RE.match(address):
                self.send_json(400, {"error": "invalid_address"})
                return

            # Build path and apply path-traversal guard
            users_dir_real = os.path.realpath(USERS_DIR)
            candidate = os.path.realpath(os.path.join(users_dir_real, address))

            # Ensure the resolved path stays inside USERS_DIR
            if not candidate.startswith(users_dir_real + os.sep):
                self.send_json(404, {"error": "miner_not_found"})
                return

            if not os.path.isfile(candidate):
                self.send_json(404, {"error": "miner_not_found"})
                return

            with open(candidate, "r", encoding="utf-8") as fh:
                raw = fh.read()

            # Validate JSON before forwarding
            parsed_json = json.loads(raw)
            self.send_json(200, parsed_json)

        except (OSError, PermissionError):
            self.send_json(404, {"error": "miner_not_found"})
        except json.JSONDecodeError:
            self.send_json(500, {"error": "invalid_data"})
        except Exception:
            # Never leak details or tracebacks
            self.send_json(500, {"error": "internal_error"})

    # Reject all other HTTP methods
    def do_POST(self): self.send_json(405, {"error": "method_not_allowed"})
    def do_PUT(self):  self.send_json(405, {"error": "method_not_allowed"})
    def do_DELETE(self): self.send_json(405, {"error": "method_not_allowed"})


def main():
    # Bind to loopback only — Tor's hidden service connects here locally
    server = http.server.HTTPServer(("127.0.0.1", PORT), MinerHandler)
    print(f"miner-server listening on 127.0.0.1:{PORT}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
