#!/usr/bin/env python3
"""
ZohoMap Nightly Sync Runner
============================
Called by the systemd timer (zohomap-sync.service) at 11pm EST every night.

Environment variables are loaded in priority order:
  1. Already set in environment (injected by systemd EnvironmentFile=/etc/zohomap/app.env)
  2. Parsed from /etc/zohomap/app.env directly (fallback for manual runs)
  3. Parsed from old-style inline Environment= lines in zohomap.service (legacy fallback)

This supports both:
  - AWS multi-instance deployments (secrets from AWS Secrets Manager via app.env)
  - Standalone Ubuntu servers (secrets from setup_secrets.sh via app.env)
"""

import os
import re
import sys
import json

# ── 1. Load from /etc/zohomap/app.env if vars are not already set ─────────────
# When run via systemd, vars are already injected. When run manually (e.g.
# sudo venv/bin/python3 run_nightly_sync.py), we need to load them ourselves.
_ENV_FILE = '/etc/zohomap/app.env'
if os.path.exists(_ENV_FILE):
    try:
        with open(_ENV_FILE) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _key, _, _val = _line.partition('=')
                    os.environ.setdefault(_key.strip(), _val.strip())
    except Exception as _e:
        print(f"[nightly] Warning: Could not read {_ENV_FILE} ({_e}) — relying on existing env vars.")
else:
    # ── 2. Legacy fallback: parse inline Environment= lines from service file ─
    _SERVICE_FILE = '/etc/systemd/system/zohomap.service'
    try:
        with open(_SERVICE_FILE) as _f:
            for _line in _f:
                _m = re.match(r'\s*Environment="([^"]+)"\s*$', _line.strip())
                if _m:
                    _kv = _m.group(1)
                    _eq = _kv.index('=') if '=' in _kv else -1
                    if _eq > 0:
                        os.environ.setdefault(_kv[:_eq], _kv[_eq + 1:])
    except Exception as _e:
        print(f"[nightly] Warning: Could not read service file ({_e}) — relying on existing env vars.")

# ── Bootstrap Flask app ───────────────────────────────────────────────────────
os.chdir('/var/www/zohomap')
sys.path.insert(0, '/var/www/zohomap')
os.environ.setdefault('FLASK_APP', 'app.py')

from app import app, do_nightly_sync

# ── Run sync inside Flask application context ─────────────────────────────────
module_filter = sys.argv[1] if len(sys.argv) > 1 else None

with app.app_context():
    # If a specific module is requested, treat as manual/override run
    is_manual = bool(module_filter)
    result = do_nightly_sync(is_manual=is_manual, module_filter=module_filter)
    print(json.dumps(result, indent=2))
    if 'error' in result:
        sys.exit(1)
