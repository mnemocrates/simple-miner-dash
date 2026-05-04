# simple-miner-dash

A privacy-preserving dashboard for ckpool solo mining statistics. The stratum node's IP address is never exposed to the public internet — all communication between the public dashboard and the stratum node travels over Tor.

## Architecture

```
Browser
  │  HTTPS
  ▼
Public nginx host
  │  fastcgi (loopback)
  ▼
miner_proxy.py (CGI script)
  │  SOCKS5 via local Tor (127.0.0.1:9050)
  ▼
Tor network
  │
  ▼
<onion-address>.onion  ←── Tor hidden service on stratum node
  │  localhost
  ▼
server.py (127.0.0.1:5000)
  │  filesystem read
  ▼
/var/log/ckpool-solo/users/<bitcoin-address>
```

The stratum node never opens a public port. `server.py` binds exclusively to `127.0.0.1`. Tor handles all circuit management; the public host's nginx only ever talks to its own `miner_proxy.py` CGI script over a Unix socket.

## Repository Structure

```
simple-miner-dash/
├── dashboard/                  ← Deploy to public nginx web root
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
│
├── stratum-node/               ← Deploy on the stratum (ckpool) node
│   ├── server.py               ← HTTP service; reads ckpool user log files
│   ├── miner-server.service    ← systemd unit for server.py
│   └── torrc.snippet           ← Tor hidden service config; append to /etc/tor/torrc
│
└── nginx-host/                 ← Deploy on the public nginx host
    ├── cgi-bin/
    │   └── miner_proxy.py      ← CGI proxy; fetches from .onion via Tor SOCKS5
    └── nginx.conf.example      ← nginx config snippet
```

---

## Prerequisites

### Both hosts
- Tor installed and running (`apt install tor`, `systemctl enable --now tor`)

### Stratum node
- Python 3.6+ (stdlib only — no additional packages needed)

### Public nginx host
- nginx with fcgiwrap: `apt install nginx fcgiwrap`
- Python 3 with requests and SOCKS support: `pip install requests[socks]`
  *(or `apt install python3-requests python3-socks`)*
- Tor running locally for SOCKS5 access (port 9050 by default)

---

## Stratum Node Setup

### 1. Create a low-privilege service user
```bash
sudo useradd -r -s /usr/sbin/nologin miner-svc
```

### 2. Install the server script
```bash
sudo mkdir -p /opt/miner-service
sudo cp stratum-node/server.py /opt/miner-service/server.py
sudo chown root:miner-svc /opt/miner-service/server.py
sudo chmod 750 /opt/miner-service/server.py
```

### 3. Configure the script
Edit `/opt/miner-service/server.py` and set:
```python
PORT      = 5000                          # keep default unless another service uses it
USERS_DIR = "/var/log/ckpool-solo/users"  # adjust for your ckpool instance
```

### 4. Grant read access to the log directory
```bash
sudo setfacl -R -m u:miner-svc:rX /var/log/ckpool-solo/users
# Or without ACLs:
# sudo chown -R ckpool:miner-svc /var/log/ckpool-solo/users
# sudo chmod -R 640 /var/log/ckpool-solo/users
# sudo chmod 750 /var/log/ckpool-solo/users
```

### 5. Install and start the systemd unit
```bash
sudo cp stratum-node/miner-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now miner-server
sudo systemctl status miner-server
```

### 6. Configure the Tor hidden service
```bash
sudo tee -a /etc/tor/torrc < stratum-node/torrc.snippet
sudo systemctl reload tor
```

Wait a few seconds for Tor to generate the hidden service keys, then read the assigned `.onion` address:
```bash
sudo cat /var/lib/tor/miner-service/hostname
# e.g.: abcdefghijklmnop.onion
```

**Save this address** — you will need it in the next section.

---

## Public Nginx Host Setup

### 1. Install dependencies
```bash
sudo apt install nginx fcgiwrap python3-pip
pip install requests[socks]
# or: apt install python3-requests python3-socks
```

### 2. Create the web root and copy files
```bash
sudo mkdir -p /var/www/miner-dash/dashboard
sudo mkdir -p /var/www/miner-dash/cgi-bin

sudo cp -r dashboard/* /var/www/miner-dash/dashboard/
sudo cp nginx-host/cgi-bin/miner_proxy.py /var/www/miner-dash/cgi-bin/
sudo chmod +x /var/www/miner-dash/cgi-bin/miner_proxy.py
```

### 3. Configure the proxy script
Edit `/var/www/miner-dash/cgi-bin/miner_proxy.py` and set:
```python
ONION_ADDRESS = "abcdefghijklmnop.onion"  # from stratum node step 6
ONION_PORT    = 80
TOR_SOCKS_PORT = 9050
```

### 4. Configure nginx
```bash
sudo cp nginx-host/nginx.conf.example /etc/nginx/sites-available/miner-dash
sudo ln -s /etc/nginx/sites-available/miner-dash /etc/nginx/sites-enabled/
```

Edit `/etc/nginx/sites-available/miner-dash` and update:
- `server_name` — your public domain name
- `ssl_certificate` / `ssl_certificate_key` — your TLS cert paths (or run certbot)

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 5. Enable fcgiwrap
```bash
sudo systemctl enable --now fcgiwrap
```

---

## Verification

### On the stratum node
```bash
# Test the HTTP service directly (no Tor)
curl "http://127.0.0.1:5000/?address=<your-bitcoin-address>"
# Expected: JSON miner stats

# Test path traversal protection
curl "http://127.0.0.1:5000/?address=../../etc/passwd"
# Expected: {"error": "invalid_address"}
```

### On the public nginx host
```bash
# Test the .onion reachability through Tor
torsocks curl "http://<onion-address>.onion/?address=<your-bitcoin-address>"
# Expected: JSON miner stats

# Test the CGI proxy script directly
QUERY_STRING="address=<your-bitcoin-address>" python3 /var/www/miner-dash/cgi-bin/miner_proxy.py
# Expected: CGI headers + JSON body

# Test the full nginx stack
curl "https://miner.example.com/api/miner?address=<your-bitcoin-address>"
# Expected: JSON miner stats
```

### In the browser
1. Navigate to `https://miner.example.com`
2. Enter a known Bitcoin address → miner statistics should display
3. Select a specific worker from the dropdown → worker-specific stats appear
4. Enter an unknown address → "Miner not found" message appears
5. Check mobile layout (browser dev tools at 375 px width)

---

## Security Notes

- `server.py` binds to `127.0.0.1` only and is additionally hardened by systemd (`IPAddressDeny=any`, `IPAddressAllow=127.0.0.1/8`, `ProtectSystem=strict`)
- Both `server.py` and `miner_proxy.py` apply the same strict Bitcoin address regex and `os.path.realpath` path-traversal guard independently
- The `.onion` address is stored only in `miner_proxy.py` on the public host — it is never sent to the browser
- `socks5h` (not `socks5`) is used so `.onion` DNS never touches the local resolver
- The nginx config rate-limits `/api/miner` to 20 requests/minute per IP
- Error responses never include filesystem paths, tracebacks, or the `.onion` address
