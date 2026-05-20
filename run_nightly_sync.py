#!/usr/bin/env python3
"""
ZohoMap Nightly Sync Runner
============================
Called by the systemd timer (zohomap-sync.service) at 11pm EST every night.
Reads environment variables from the zohomap systemd service file so it
has the same configuration (DATABASE_URI, ZOHO_*, etc.) as the main app.
"""

import os
import re
import sys
import json

# ── Load environment from the systemd service file ────────────────────────────
_SERVICE_FILE = '/etc/systemd/system/zohomap.service'
try:
    with open(_SERVICE_FILE) as _f:
        for _line in _f:
            # Match lines like: Environment="KEY=value"
            _m = re.match(r'\s*Environment="([^"]+)"\s*$', _line.strip())
            if _m:
                _kv = _m.group(1)
                _eq = _kv.index('=') if '=' in _kv else -1
                if _eq > 0:
                    _key = _kv[:_eq]
                    _val = _kv[_eq + 1:]
                    os.environ.setdefault(_key, _val)
except Exception as _e:
    print(f"[nightly] Warning: Could not read service file ({_e}) — relying on existing env vars.")

# ── Bootstrap Flask app ───────────────────────────────────────────────────────
os.chdir('/var/www/zohomap')
sys.path.insert(0, '/var/www/zohomap')
os.environ.setdefault('FLASK_APP', 'app.py')

from app import app, do_nightly_sync

# ── Run sync inside Flask application context ─────────────────────────────────
with app.app_context():
    result = do_nightly_sync()
    print(json.dumps(result, indent=2))
    if 'error' in result:
        sys.exit(1)
