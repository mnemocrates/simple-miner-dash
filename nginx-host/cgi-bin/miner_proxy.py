#!/usr/bin/env python3
"""
miner_proxy.py — CGI proxy for simple-miner-dash (public nginx host).

Receives a Bitcoin address from nginx, fetches the miner status from the
stratum node's Tor hidden service via the local Tor SOCKS5 proxy, and
returns the JSON response to the browser.

Dependencies (public nginx host only):
    pip install requests[socks]
    # or: apt install python3-requests python3-socks

Configuration: edit the constants below.
"""

import os
import re
import sys
import json

# ── Configuration ─────────────────────────────────────────────────────────────
# .onion address of the stratum node's hidden service.
# Obtain this after running:  sudo cat /var/lib/tor/miner-service/hostname
ONION_ADDRESS = "changeme.onion"

# Port the hidden service is exposed on (matches HiddenServicePort in torrc.snippet)
ONION_PORT = 80

# Local Tor SOCKS5 proxy port (default Tor install: 9050)
TOR_SOCKS_PORT = 9050

# Request timeout in seconds. Tor circuit establishment can take 5–15 s.
REQUEST_TIMEOUT = 25

# Strict Bitcoin address regex — mirrors server.py and app.js
ADDRESS_RE = re.compile(r'^(bc1[a-z0-9]{25,90}|[13][a-zA-Z0-9]{25,34})$')
# ─────────────────────────────────────────────────────────────────────────────


def send_cgi_json(status: int, payload: dict) -> None:
    """Write CGI response and exit."""
    print(f"Status: {status}")
    print("Content-Type: application/json")
    print("Cache-Control: no-store")
    print("")
    print(json.dumps(payload))
    sys.exit(0)


def main() -> None:
    # Parse address from QUERY_STRING
    qs = os.environ.get("QUERY_STRING", "")
    params: dict = {}
    for part in qs.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
            params[k] = v

    address = params.get("address", "").strip()

    # Validate address (defense in depth — nginx already rate-limits the endpoint)
    if not address or not ADDRESS_RE.match(address):
        send_cgi_json(400, {"error": "invalid_address"})

    # Import here so a missing package gives a clear 500 rather than crashing CGI
    try:
        import requests
    except ImportError:
        send_cgi_json(500, {"error": "internal_error"})

    # Build the upstream URL — address is already validated, safe to interpolate
    upstream_url = (
        f"http://{ONION_ADDRESS}:{ONION_PORT}/"
        f"?address={address}"
    )

    # Route the request through the local Tor SOCKS5 proxy.
    # socks5h (not socks5) ensures DNS resolution happens inside Tor,
    # so the .onion hostname never touches the local resolver.
    proxies = {
        "http":  f"socks5h://127.0.0.1:{TOR_SOCKS_PORT}",
        "https": f"socks5h://127.0.0.1:{TOR_SOCKS_PORT}",
    }

    try:
        resp = requests.get(
            upstream_url,
            proxies=proxies,
            timeout=REQUEST_TIMEOUT,
            # Only plain HTTP to the .onion — Tor itself encrypts the circuit
            verify=False,
        )
        # Forward the upstream status and body directly
        try:
            payload = resp.json()
        except ValueError:
            send_cgi_json(500, {"error": "invalid_data"})

        send_cgi_json(resp.status_code, payload)

    except requests.exceptions.Timeout:
        send_cgi_json(504, {"error": "upstream_timeout"})
    except requests.exceptions.ConnectionError:
        send_cgi_json(502, {"error": "upstream_unreachable"})
    except Exception:
        send_cgi_json(500, {"error": "internal_error"})


try:
    main()
except SystemExit:
    raise
except Exception:
    try:
        print("Status: 500")
        print("Content-Type: application/json")
        print("")
        print(json.dumps({"error": "internal_error"}))
    except Exception:
        pass
    sys.exit(1)
