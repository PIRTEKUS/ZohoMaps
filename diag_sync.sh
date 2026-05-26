#!/bin/bash
# ============================================================
#  ZohoMap Sync Diagnostics
#  Run as:  sudo bash /var/www/zohomap/diag_sync.sh
# ============================================================

APPDIR="/var/www/zohomap"
VENV="$APPDIR/venv/bin/python3"
DBFILE="$APPDIR/database.db"
SERVICE="zohomap"
SYNC_SVC="zohomap-sync"
SYNC_TIMER="zohomap-sync.timer"
LOGFILE="$APPDIR/debug.log"
JOURNAL_LINES=40

C_RESET='\033[0m'
C_GREEN='\033[0;32m'
C_RED='\033[0;31m'
C_YELLOW='\033[0;33m'
C_CYAN='\033[0;36m'
C_BOLD='\033[1m'

ok()   { echo -e "  ${C_GREEN}✅  $*${C_RESET}"; }
fail() { echo -e "  ${C_RED}❌  $*${C_RESET}"; }
warn() { echo -e "  ${C_YELLOW}⚠️   $*${C_RESET}"; }
info() { echo -e "  ${C_CYAN}ℹ️   $*${C_RESET}"; }
hdr()  { echo -e "\n${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"; echo -e "${C_BOLD}  $*${C_RESET}"; echo -e "${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"; }

cd "$APPDIR" || { echo "ERROR: $APPDIR not found"; exit 1; }

# ── 1. Main App Service ──────────────────────────────────────
hdr "1. Main App Service (zohomap)"

SVC_STATUS=$(systemctl is-active "$SERVICE" 2>/dev/null)
if [ "$SVC_STATUS" = "active" ]; then
    ok "zohomap.service is ACTIVE"
else
    fail "zohomap.service is NOT active (status: $SVC_STATUS)"
    echo ""
    echo "    Last journal entries:"
    sudo journalctl -u "$SERVICE" -n 20 --no-pager 2>/dev/null | sed 's/^/    /'
fi

GUNICORN_WORKERS=$(pgrep -c -f "gunicorn.*app" 2>/dev/null || echo 0)
info "Gunicorn worker processes: $GUNICORN_WORKERS"
if [ "$GUNICORN_WORKERS" -gt 1 ]; then
    warn "Multiple Gunicorn workers ($GUNICORN_WORKERS) detected."
    warn "The on-demand sync button may appear stuck because the 'running' flag"
    warn "lives in-memory per-worker. Each request may hit a different worker."
    warn "FIX: The DB flag 'nightly_sync_running' is the authoritative state —"
    warn "     the UI should rely on that, not the per-worker in-memory flag."
fi

# ── 2. Nightly Sync Timer ───────────────────────────────────
hdr "2. Nightly Sync Timer"

TIMER_STATUS=$(systemctl is-active "$SYNC_TIMER" 2>/dev/null)
TIMER_ENABLED=$(systemctl is-enabled "$SYNC_TIMER" 2>/dev/null)

if [ "$TIMER_STATUS" = "active" ]; then
    ok "zohomap-sync.timer is ACTIVE"
else
    fail "zohomap-sync.timer is NOT active (status: $TIMER_STATUS)"
    echo "    FIX: sudo systemctl enable --now zohomap-sync.timer"
fi

if [ "$TIMER_ENABLED" = "enabled" ]; then
    ok "zohomap-sync.timer is ENABLED (survives reboots)"
else
    warn "zohomap-sync.timer is NOT enabled for auto-start"
    echo "    FIX: sudo systemctl enable zohomap-sync.timer"
fi

echo ""
echo "  Timer schedule:"
systemctl list-timers "$SYNC_TIMER" --no-pager 2>/dev/null | grep -v "^$" | sed 's/^/    /'

# ── 3. Last Nightly Sync Service Run ────────────────────────
hdr "3. Last Nightly Sync Service Run"

LAST_RUN=$(systemctl show "$SYNC_SVC" --property=ExecMainExitTimestamp 2>/dev/null | cut -d= -f2)
LAST_RESULT=$(systemctl show "$SYNC_SVC" --property=Result 2>/dev/null | cut -d= -f2)

if [ -z "$LAST_RUN" ] || [ "$LAST_RUN" = "0" ]; then
    warn "No record of zohomap-sync.service ever running"
else
    info "Last run:    $LAST_RUN"
    if [ "$LAST_RESULT" = "success" ]; then
        ok "Last result: success"
    else
        fail "Last result: $LAST_RESULT"
    fi
fi

echo ""
echo "  Last $JOURNAL_LINES journal lines for zohomap-sync:"
sudo journalctl -u "$SYNC_SVC" -n "$JOURNAL_LINES" --no-pager 2>/dev/null | sed 's/^/    /'

# ── 4. Manual sync dry-run ──────────────────────────────────
hdr "4. Manual Sync Test (dry-run)"
info "Running run_nightly_sync.py directly as www-data..."
echo ""
sudo -u www-data "$VENV" "$APPDIR/run_nightly_sync.py" 2>&1 | tail -60 | sed 's/^/    /'
echo ""
SYNC_EXIT=${PIPESTATUS[0]}
if [ "$SYNC_EXIT" -eq 0 ]; then
    ok "Manual sync exited with code 0 (success)"
else
    fail "Manual sync exited with code $SYNC_EXIT"
fi

# ── 5. Admin Token Check ─────────────────────────────────────
hdr "5. Admin Token Check"

HAS_DB_TOKEN=$("$VENV" -c "
import sys; sys.path.insert(0, '$APPDIR')
import os; os.chdir('$APPDIR')
try:
    import database
    val = database.get_global_setting('admin_refresh_token', '')
    print('yes' if val else 'no')
except Exception as e:
    print(f'error: {e}')
" 2>/dev/null)

if [ "$HAS_DB_TOKEN" = "yes" ]; then
    ok "admin_refresh_token found in DB"
elif [ "$HAS_DB_TOKEN" = "no" ]; then
    fail "admin_refresh_token is MISSING from DB"
    warn "Fix: Log in as admin at least once via the browser to store the token."
else
    warn "Could not check DB token: $HAS_DB_TOKEN"
fi

ENV_TOKEN=$(sudo grep -oP '(?<=ZOHO_REFRESH_TOKEN=)[^"]+' /etc/systemd/system/zohomap.service 2>/dev/null | head -1)
if [ -n "$ENV_TOKEN" ]; then
    ok "ZOHO_REFRESH_TOKEN found in zohomap.service (env backup)"
else
    info "ZOHO_REFRESH_TOKEN not set in zohomap.service (DB token is used — this is fine)"
fi

# ── 6. DB State ─────────────────────────────────────────────
hdr "6. Database State"

if [ -f "$DBFILE" ]; then
    ok "database.db found"
    DB_SIZE=$(du -sh "$DBFILE" | cut -f1)
    info "DB size: $DB_SIZE"

    echo ""
    echo "  Key global_settings values:"
    sqlite3 "$DBFILE" "
        SELECT key, substr(value,1,80) as value
        FROM global_settings
        WHERE key IN (
            'schema_version',
            'last_nightly_sync',
            'last_nightly_sync_results',
            'nightly_sync_running',
            'crmplus_orgid',
            'crmplus_domain',
            'cached_module_url_map'
        )
        ORDER BY key;" 2>/dev/null | column -t -s '|' | sed 's/^/    /'

    echo ""
    echo "  Shared module configs (used by nightly sync):"
    sqlite3 "$DBFILE" "
        SELECT module_name, is_shared, user_id
        FROM module_config
        ORDER BY module_name;" 2>/dev/null | column -t -s '|' | sed 's/^/    /'
    SHARED_COUNT=$(sqlite3 "$DBFILE" "SELECT COUNT(*) FROM module_config WHERE is_shared=1;" 2>/dev/null)
    if [ "$SHARED_COUNT" = "0" ] || [ -z "$SHARED_COUNT" ]; then
        fail "No shared module configs found! Nightly sync will do nothing."
        warn "Fix: In Settings, mark at least one module config as 'shared'."
    else
        ok "$SHARED_COUNT shared module config(s) found"
    fi

    echo ""
    echo "  Global cache record counts:"
    sqlite3 "$DBFILE" "
        SELECT module_name, COUNT(*) as records
        FROM module_records
        WHERE user_id = '__global__'
        GROUP BY module_name;" 2>/dev/null | column -t -s '|' | sed 's/^/    /' || info "(no global cache records yet)"
else
    fail "database.db NOT found at $DBFILE"
fi

# ── 7. Zoho API Connectivity ─────────────────────────────────
hdr "7. Zoho API Connectivity"

ZOHO_API_URL=$(sudo grep -oP '(?<=ZOHO_API_URL=)[^"]+' /etc/systemd/system/zohomap.service 2>/dev/null | head -1)
ZOHO_API_URL="${ZOHO_API_URL:-https://www.zohoapis.com}"
ACCOUNTS_URL=$(sudo grep -oP '(?<=ZOHO_ACCOUNTS_URL=)[^"]+' /etc/systemd/system/zohomap.service 2>/dev/null | head -1)
ACCOUNTS_URL="${ACCOUNTS_URL:-https://accounts.zoho.com}"

for url in "$ZOHO_API_URL" "$ACCOUNTS_URL" "https://www.google.com"; do
    HTTP=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 8 "$url" 2>/dev/null || echo "000")
    if [ "$HTTP" != "000" ] && [ "$HTTP" != "502" ] && [ "$HTTP" != "503" ]; then
        ok "Reachable: $url (HTTP $HTTP)"
    else
        fail "UNREACHABLE: $url (HTTP $HTTP)"
    fi
done

# ── 8. Recent debug.log errors ─────────────────────────────
hdr "8. Recent Errors in debug.log"

if [ -f "$LOGFILE" ]; then
    echo "  Last 30 ERROR/WARNING lines from debug.log:"
    grep -iE "error|fail|exception|traceback|403|401|500|timeout" "$LOGFILE" 2>/dev/null \
        | tail -30 | sed 's/^/    /'
    echo ""
    echo "  Last 20 nightly sync log lines:"
    grep -i "\[nightly\]" "$LOGFILE" 2>/dev/null | tail -20 | sed 's/^/    /'
else
    warn "debug.log not found at $LOGFILE"
fi

# ── 9. Permissions ──────────────────────────────────────────
hdr "9. File Permissions"

OWNER=$(stat -c '%U:%G' "$APPDIR" 2>/dev/null)
info "App directory owner: $OWNER"

for path in "$DBFILE" "$LOGFILE" "$APPDIR/static/custom_markers"; do
    if [ -e "$path" ]; then
        PERM=$(stat -c '%U:%G %a' "$path" 2>/dev/null)
        FOWNER=$(stat -c '%U' "$path" 2>/dev/null)
        if [ "$FOWNER" = "www-data" ] || [ "$FOWNER" = "root" ]; then
            ok "$path → $PERM"
        else
            warn "$path → $PERM  (expected owner: www-data)"
        fi
    else
        warn "$path → NOT FOUND"
    fi
done

# ── Summary ─────────────────────────────────────────────────
hdr "Diagnostics Complete"
echo ""
echo "  To watch live sync output, run:"
echo "    sudo journalctl -u zohomap-sync -f"
echo ""
echo "  To trigger the nightly sync manually right now:"
echo "    sudo systemctl start zohomap-sync.service"
echo ""
echo "  To watch the debug log live:"
echo "    tail -f $LOGFILE"
echo ""
