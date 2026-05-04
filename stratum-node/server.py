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

# Pool registry.  Each key becomes the ?pool= URL parameter.
# To add a new ckpool instance, append an entry here and update
# ReadOnlyPaths in miner-server.service and ALLOWED_POOLS in miner_proxy.py.
POOLS = {
    "default": {
        "label":       "Default",
        "users_dir":   "/var/log/ckpool-solo/users",
        "status_file": "/var/log/ckpool-solo/pool/pool.status",
    },
    "lhr": {
        "label":       "LHR",
        "users_dir":   "/var/log/ckpool-solo-lhr/users",
        "status_file": "/var/log/ckpool-solo-lhr/pool/pool.status",
    },
}

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
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/pools":
            self._serve_pools_list()
        elif parsed.path == "/pool":
            params = urllib.parse.parse_qs(parsed.query)
            self._serve_pool_stats(params)
        else:
            params = urllib.parse.parse_qs(parsed.query)
            self._serve_miner_stats(params)

    def _serve_pools_list(self):
        """Return the list of configured pool keys and labels."""
        try:
            payload = [{"key": k, "label": v["label"]} for k, v in POOLS.items()]
            self.send_json(200, payload)
        except Exception:
            self.send_json(500, {"error": "internal_error"})

    def _serve_pool_stats(self, params):
        """Return merged pool.status JSON for the requested pool."""
        try:
            pool_list = params.get("pool", ["default"])
            pool = pool_list[0].strip()
            if pool not in POOLS:
                self.send_json(400, {"error": "invalid_pool"})
                return

            # Path is entirely from the hardcoded POOLS dict — no user input
            status_file = POOLS[pool]["status_file"]

            with open(status_file, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()

            # pool.status contains one JSON object per line; merge them all
            merged = {}
            for line in lines:
                line = line.strip()
                if line:
                    merged.update(json.loads(line))

            self.send_json(200, merged)

        except (OSError, PermissionError):
            self.send_json(404, {"error": "pool_stats_unavailable"})
        except json.JSONDecodeError:
            self.send_json(500, {"error": "invalid_data"})
        except Exception:
            self.send_json(500, {"error": "internal_error"})

    def _serve_miner_stats(self, params):
        """Return the ckpool user log JSON for the requested address and pool."""
        try:
            address_list = params.get("address", [])

            if not address_list:
                self.send_json(400, {"error": "invalid_address"})
                return

            address = address_list[0].strip()

            # Validate address format
            if not ADDRESS_RE.match(address):
                self.send_json(400, {"error": "invalid_address"})
                return

            # Validate and resolve pool
            pool_list = params.get("pool", ["default"])
            pool = pool_list[0].strip()
            if pool not in POOLS:
                self.send_json(400, {"error": "invalid_pool"})
                return
            users_dir = POOLS[pool]["users_dir"]

            # Build path and apply path-traversal guard
            users_dir_real = os.path.realpath(users_dir)
            candidate = os.path.realpath(os.path.join(users_dir_real, address))

            # Ensure the resolved path stays inside the selected users_dir
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
