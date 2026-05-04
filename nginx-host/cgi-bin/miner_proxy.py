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

# Whitelist of valid pool keys — must match POOLS keys in server.py
# Defense-in-depth: server.py validates independently.
ALLOWED_POOLS = {"default", "lhr"}
# ─────────────────────────────────────────────────────────────────────────────


def send_cgi_json(status: int, payload) -> None:
    """Write CGI response and exit."""
    print(f"Status: {status}")
    print("Content-Type: application/json")
    print("Cache-Control: no-store")
    print("")
    print(json.dumps(payload))
    sys.exit(0)


def _parse_qs() -> dict:
    """Parse QUERY_STRING into a flat key→value dict."""
    qs = os.environ.get("QUERY_STRING", "")
    params: dict = {}
    for part in qs.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
            params[k] = v
    return params


def _tor_get(path: str) -> "requests.Response":
    """Fetch a path on the onion service via Tor SOCKS5."""
    import requests as _requests
    proxies = {
        "http":  f"socks5h://127.0.0.1:{TOR_SOCKS_PORT}",
        "https": f"socks5h://127.0.0.1:{TOR_SOCKS_PORT}",
    }
    return _requests.get(
        f"http://{ONION_ADDRESS}:{ONION_PORT}{path}",
        proxies=proxies,
        timeout=REQUEST_TIMEOUT,
        verify=False,
    )


def serve_pools_list() -> None:
    """Forward /pools metadata from the stratum node (no user input)."""
    try:
        import requests  # noqa: F401 — trigger ImportError early if missing
    except ImportError:
        send_cgi_json(500, {"error": "internal_error"})
    try:
        resp = _tor_get("/pools")
        try:
            payload = resp.json()
        except ValueError:
            send_cgi_json(500, {"error": "invalid_data"})
        send_cgi_json(resp.status_code, payload)
    except ImportError:
        send_cgi_json(500, {"error": "internal_error"})
    except Exception as exc:
        import requests as _req
        if isinstance(exc, _req.exceptions.Timeout):
            send_cgi_json(504, {"error": "upstream_timeout"})
        elif isinstance(exc, _req.exceptions.ConnectionError):
            send_cgi_json(502, {"error": "upstream_unreachable"})
        else:
            send_cgi_json(500, {"error": "internal_error"})


def serve_pool_stats(params: dict) -> None:
    """Forward /pool stats for the requested pool."""
    try:
        import requests  # noqa: F401
    except ImportError:
        send_cgi_json(500, {"error": "internal_error"})

    pool = params.get("pool", "default").strip()
    if pool not in ALLOWED_POOLS:
        send_cgi_json(400, {"error": "invalid_pool"})

    try:
        resp = _tor_get(f"/pool?pool={pool}")
        try:
            payload = resp.json()
        except ValueError:
            send_cgi_json(500, {"error": "invalid_data"})
        send_cgi_json(resp.status_code, payload)
    except ImportError:
        send_cgi_json(500, {"error": "internal_error"})
    except Exception as exc:
        import requests as _req
        if isinstance(exc, _req.exceptions.Timeout):
            send_cgi_json(504, {"error": "upstream_timeout"})
        elif isinstance(exc, _req.exceptions.ConnectionError):
            send_cgi_json(502, {"error": "upstream_unreachable"})
        else:
            send_cgi_json(500, {"error": "internal_error"})


def serve_miner_stats(params: dict) -> None:
    """Forward miner user stats for the requested address and pool."""
    address = params.get("address", "").strip()

    # Validate address (defense in depth — nginx already rate-limits the endpoint)
    if not address or not ADDRESS_RE.match(address):
        send_cgi_json(400, {"error": "invalid_address"})

    # Validate pool (defense in depth — server.py validates independently)
    pool = params.get("pool", "default").strip()
    if pool not in ALLOWED_POOLS:
        send_cgi_json(400, {"error": "invalid_pool"})

    try:
        import requests  # noqa: F401
    except ImportError:
        send_cgi_json(500, {"error": "internal_error"})

    try:
        resp = _tor_get(f"/?address={address}&pool={pool}")
        try:
            payload = resp.json()
        except ValueError:
            send_cgi_json(500, {"error": "invalid_data"})
        send_cgi_json(resp.status_code, payload)
    except ImportError:
        send_cgi_json(500, {"error": "internal_error"})
    except Exception as exc:
        import requests as _req
        if isinstance(exc, _req.exceptions.Timeout):
            send_cgi_json(504, {"error": "upstream_timeout"})
        elif isinstance(exc, _req.exceptions.ConnectionError):
            send_cgi_json(502, {"error": "upstream_unreachable"})
        else:
            send_cgi_json(500, {"error": "internal_error"})


def main() -> None:
    params = _parse_qs()
    uri = os.environ.get("REQUEST_URI", "")

    if uri.startswith("/api/pools"):
        serve_pools_list()
    elif uri.startswith("/api/pool"):
        serve_pool_stats(params)
    else:
        serve_miner_stats(params)


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
