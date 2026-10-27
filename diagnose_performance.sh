#!/bin/bash
# ==============================================================================
#  ZohoMap Ubuntu Server Performance & Gateway Error Diagnostics
# ==============================================================================
#  Usage:
#    sudo bash /var/www/zohomap/diagnose_performance.sh
#    sudo bash /var/www/zohomap/diagnose_performance.sh --quick-fix
# ==============================================================================

set -o pipefail

APP_DIR="/var/www/zohomap"
VENV_PY="$APP_DIR/venv/bin/python3"
ENV_FILE="/etc/zohomap/app.env"
NGINX_ERR_LOG="/var/log/nginx/error.log"
NGINX_ACC_LOG="/var/log/nginx/access.log"
DEBUG_LOG="$APP_DIR/debug.log"
DB_FILE="$APP_DIR/database.db"
WAL_FILE="$APP_DIR/database.db-wal"
SOCK_FILE="$APP_DIR/zohomap.sock"

# Color Codes
C_RESET='\033[0m'
C_BOLD='\033[1m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_CYAN='\033[0;36m'
C_MAGENTA='\033[0;35m'

ok()   { echo -e "  ${C_GREEN}✅ [OK]${C_RESET} $*"; }
warn() { echo -e "  ${C_YELLOW}⚠️  [WARNING]${C_RESET} $*"; }
fail() { echo -e "  ${C_RED}❌ [CRITICAL]${C_RESET} $*"; }
info() { echo -e "  ${C_CYAN}ℹ️  [INFO]${C_RESET} $*"; }
hdr()  {
    echo -e "\n${C_BOLD}${C_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
    echo -e "${C_BOLD}  $*${C_RESET}"
    echo -e "${C_BOLD}${C_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
}

CRITICAL_ISSUES=()
WARNING_ISSUES=()

cd "$APP_DIR" 2>/dev/null || {
    echo -e "${C_RED}Error: App directory $APP_DIR not found.${C_RESET}"
    exit 1
}

# Ensure system tools are available in PATH
SYS_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH="$SYS_PATH:$PATH"

# Load environment if present (without allowing it to clobber system PATH)
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE" 2>/dev/null || true
    set +a
fi
# Re-ensure system PATH is prioritized over any venv PATH set in app.env
export PATH="$SYS_PATH:$APP_DIR/venv/bin:$PATH"

echo -e "\n${C_BOLD}${C_MAGENTA}╔══════════════════════════════════════════════════════════════════╗${C_RESET}"
echo -e "${C_BOLD}${C_MAGENTA}║           ZohoMap Performance & Gateway Diagnostics             ║${C_RESET}"
echo -e "${C_BOLD}${C_MAGENTA}╚══════════════════════════════════════════════════════════════════╝${C_RESET}"
echo -e "  Timestamp : $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo -e "  Host      : $(hostname) ($(uname -r))"
echo -e "  Directory : $APP_DIR"

# ==============================================================================
#  1. SYSTEM RESOURCES (CPU, MEMORY, SWAP, DISK)
# ==============================================================================
hdr "1. System Resources & Hardware Pressure"

# 1.1 CPU & Load Average
CPU_CORES=$(nproc 2>/dev/null || echo 1)
LOAD_1M=$(awk '{print $1}' /proc/loadavg 2>/dev/null || uptime | awk -F'load average:' '{ print $2 }' | cut -d, -f1 | tr -d ' ')
LOAD_5M=$(awk '{print $2}' /proc/loadavg 2>/dev/null || echo 0)
LOAD_15M=$(awk '{print $3}' /proc/loadavg 2>/dev/null || echo 0)
info "CPU Cores: $CPU_CORES | Load Average: $LOAD_1M (1m), $LOAD_5M (5m), $LOAD_15M (15m)"

LOAD_INT=$(echo "$LOAD_1M" | awk '{print int($1)}')
if [ "$LOAD_INT" -gt "$((CPU_CORES * 2))" ]; then
    fail "High CPU Load ($LOAD_1M on $CPU_CORES cores). Server is CPU-throttled!"
    CRITICAL_ISSUES+=("High CPU load ($LOAD_1M on $CPU_CORES cores) causing slow response times and timeouts.")
elif [ "$LOAD_INT" -ge "$CPU_CORES" ]; then
    warn "CPU Load ($LOAD_1M) is near or at total core capacity ($CPU_CORES cores)."
    WARNING_ISSUES+=("CPU Load ($LOAD_1M) near capacity.")
else
    ok "CPU load is within normal operating thresholds."
fi

# 1.2 Memory & Swap
TOTAL_RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
AVAIL_RAM_MB=$(free -m | awk '/^Mem:/{print $7}')
USED_RAM_MB=$((TOTAL_RAM_MB - AVAIL_RAM_MB))
TOTAL_SWAP_MB=$(free -m | awk '/^Swap:/{print $2}')
USED_SWAP_MB=$(free -m | awk '/^Swap:/{print $3}')

info "RAM Total: ${TOTAL_RAM_MB}MB | Used: ${USED_RAM_MB}MB | Available: ${AVAIL_RAM_MB}MB"
if [ "$AVAIL_RAM_MB" -lt 250 ]; then
    fail "CRITICALLY LOW MEMORY: Only ${AVAIL_RAM_MB}MB RAM available out of ${TOTAL_RAM_MB}MB!"
    CRITICAL_ISSUES+=("RAM exhaustion (< 250MB available). Gunicorn workers are likely being killed or thrashing.")
elif [ "$AVAIL_RAM_MB" -lt 500 ]; then
    warn "Low Memory: Only ${AVAIL_RAM_MB}MB available."
    WARNING_ISSUES+=("Low memory available (${AVAIL_RAM_MB}MB). Large responses may trigger out-of-memory.")
else
    ok "RAM capacity is healthy (${AVAIL_RAM_MB}MB available)."
fi

if [ "$TOTAL_SWAP_MB" -eq 0 ]; then
    warn "No Swap space configured on this instance! If RAM runs out, processes get killed immediately."
    WARNING_ISSUES+=("No swap file configured. OOM-killer will terminate Gunicorn on spikes.")
else
    info "Swap Total: ${TOTAL_SWAP_MB}MB | Swap Used: ${USED_SWAP_MB}MB"
    if [ "$USED_SWAP_MB" -gt 300 ]; then
        warn "Heavy Swap Usage (${USED_SWAP_MB}MB used). High disk I/O latency will cause extreme website slowness!"
        WARNING_ISSUES+=("High Swap usage (${USED_SWAP_MB}MB). Swap thrashing slows down all database and HTTP queries.")
    fi
fi

# 1.3 Out-Of-Memory (OOM) Killer Check
OOM_KILLS=$(dmesg -T 2>/dev/null | grep -iE "Out of memory|killed process" | tail -5)
if [ -z "$OOM_KILLS" ]; then
    OOM_KILLS=$(journalctl -k --since "24 hours ago" --no-pager 2>/dev/null | grep -iE "Out of memory|killed process" | tail -5)
fi
if [ -n "$OOM_KILLS" ]; then
    fail "Kernel Out-Of-Memory (OOM) killer has terminated processes recently!"
    echo -e "${C_RED}    $OOM_KILLS${C_RESET}"
    CRITICAL_ISSUES+=("Kernel OOM killer terminated Gunicorn/Python processes due to memory exhaustion.")
else
    ok "No recent Out-Of-Memory (OOM) killer events detected."
fi

# 1.4 Disk Space & Inodes
DISK_USAGE_PCT=$(df "$APP_DIR" | awk 'NR==2 {print $5}' | tr -d '%')
DISK_AVAIL=$(df -h "$APP_DIR" | awk 'NR==2 {print $4}')
INODE_USAGE_PCT=$(df -i "$APP_DIR" | awk 'NR==2 {print $5}' | tr -d '%')
info "Disk Available: $DISK_AVAIL (${DISK_USAGE_PCT}% used) | Inodes: ${INODE_USAGE_PCT}% used"

if [ "$DISK_USAGE_PCT" -ge 90 ]; then
    fail "Disk space is critically low (${DISK_USAGE_PCT}% used, $DISK_AVAIL available)!"
    CRITICAL_ISSUES+=("Disk space nearly full (${DISK_USAGE_PCT}%). Nginx/Gunicorn cannot write temporary files.")
elif [ "$DISK_USAGE_PCT" -ge 80 ]; then
    warn "Disk space is getting low (${DISK_USAGE_PCT}% used)."
fi

echo ""
echo -e "  ${C_BOLD}Top 5 Processes by Memory Usage:${C_RESET}"
ps -eo pid,user,%mem,%cpu,rss,comm --sort=-%mem | head -6 | sed 's/^/    /'

# ==============================================================================
#  2. GUNICORN APP SERVER & SYSTEMD STATUS
# ==============================================================================
hdr "2. Application Service (Gunicorn / Systemd)"

SVC_ACTIVE=$(systemctl is-active zohomap.service 2>/dev/null || echo "unknown")
if [ "$SVC_ACTIVE" = "active" ]; then
    ok "zohomap.service is ACTIVE"
else
    fail "zohomap.service is NOT ACTIVE (Status: $SVC_ACTIVE)"
    CRITICAL_ISSUES+=("zohomap.service is not running. All requests will fail with 502 Bad Gateway!")
fi

GUNICORN_PIDS=$(pgrep -f "gunicorn.*app:app" 2>/dev/null || true)
NUM_WORKERS=$(echo "$GUNICORN_PIDS" | grep -v "^$" | wc -l)
info "Running Gunicorn processes: $NUM_WORKERS"

if [ "$NUM_WORKERS" -eq 0 ]; then
    fail "No Gunicorn worker processes found running!"
    CRITICAL_ISSUES+=("Gunicorn master/workers are not running.")
else
    echo -e "  ${C_BOLD}Gunicorn Worker Memory Breakdown:${C_RESET}"
    ps -o pid,user,%cpu,%mem,rss,cmd -p $(echo $GUNICORN_PIDS | tr ' ' ',') 2>/dev/null | sed 's/^/    /'
fi

WORKER_TIMEOUTS=$(journalctl -u zohomap.service --since "3 hours ago" --no-pager 2>/dev/null | grep -iE "WORKER TIMEOUT|Worker exiting" | tail -5)
if [ -n "$WORKER_TIMEOUTS" ]; then
    fail "Gunicorn WORKER TIMEOUT events detected in the last 3 hours!"
    echo -e "${C_RED}    $WORKER_TIMEOUTS${C_RESET}"
    CRITICAL_ISSUES+=("Gunicorn workers are timing out (requests taking longer than timeout). This causes 502/504 errors.")
else
    ok "No Gunicorn worker timeout crash loops detected."
fi

if [ -S "$SOCK_FILE" ]; then
    SOCK_PERMS=$(stat -c '%U:%G %a' "$SOCK_FILE" 2>/dev/null)
    ok "Unix socket $SOCK_FILE exists ($SOCK_PERMS)"
else
    fail "Unix socket $SOCK_FILE is MISSING!"
    CRITICAL_ISSUES+=("Socket $SOCK_FILE missing. Nginx cannot forward traffic to Gunicorn.")
fi

# ==============================================================================
#  3. NGINX REVERSE PROXY & GATEWAY ERRORS (502 / 504 / 500)
# ==============================================================================
hdr "3. Nginx Web Server & Gateway Errors"

NGINX_ACTIVE=$(systemctl is-active nginx 2>/dev/null || echo "unknown")
if [ "$NGINX_ACTIVE" = "active" ]; then
    ok "Nginx service is ACTIVE"
else
    fail "Nginx service is NOT active!"
    CRITICAL_ISSUES+=("Nginx is down.")
fi

if [ -f "$NGINX_ERR_LOG" ]; then
    ERR_504_CNT=$(grep -c "upstream timed out" "$NGINX_ERR_LOG" 2>/dev/null || echo 0)
    ERR_502_REFUSED=$(grep -c "Connection refused" "$NGINX_ERR_LOG" 2>/dev/null || echo 0)
    ERR_502_UNAVAIL=$(grep -c "Resource temporarily unavailable" "$NGINX_ERR_LOG" 2>/dev/null || echo 0)
    ERR_502_PREMATURE=$(grep -c "upstream prematurely closed connection" "$NGINX_ERR_LOG" 2>/dev/null || echo 0)

    echo -e "  ${C_BOLD}Nginx Gateway Errors in $NGINX_ERR_LOG:${C_RESET}"
    echo -e "    - 504 Gateway Timeouts (upstream timed out)        : $ERR_504_CNT"
    echo -e "    - 502 Bad Gateway (Connection refused)            : $ERR_502_REFUSED"
    echo -e "    - 502 Bad Gateway (Resource temporarily unavail)  : $ERR_502_UNAVAIL"
    echo -e "    - 502 Bad Gateway (Upstream prematurely closed)   : $ERR_502_PREMATURE"

    if [ "$ERR_504_CNT" -gt 0 ]; then
        warn "Found $ERR_504_CNT occurrences of 504 Gateway Timeouts. Requests are exceeding Nginx proxy_read_timeout!"
        WARNING_ISSUES+=("Nginx 504 Gateway Timeouts found. Backend queries/API calls are taking too long.")
    fi
    if [ "$ERR_502_REFUSED" -gt 0 ] || [ "$ERR_502_PREMATURE" -gt 0 ] || [ "$ERR_502_UNAVAIL" -gt 0 ]; then
        fail "Found 502 Bad Gateway errors. Gunicorn workers crashed, restarted, or were overwhelmed!"
        CRITICAL_ISSUES+=("Nginx 502 Bad Gateway errors detected in error.log.")
    fi

    echo ""
    echo -e "  ${C_BOLD}Last 8 error lines from Nginx error.log:${C_RESET}"
    tail -8 "$NGINX_ERR_LOG" 2>/dev/null | sed 's/^/    /' || echo "    (none)"
else
    warn "Nginx error log not found at $NGINX_ERR_LOG"
fi

if [ -f "$NGINX_ACC_LOG" ]; then
    echo ""
    echo -e "  ${C_BOLD}Recent HTTP Status Codes in $NGINX_ACC_LOG (sample of 1,000 requests):${C_RESET}"
    tail -n 1000 "$NGINX_ACC_LOG" 2>/dev/null | awk '{print $9}' | sort | uniq -c | sort -nr | head -8 | sed 's/^/    /'
fi

# ==============================================================================
#  4. APPLICATION LOGS & PYTHON EXCEPTIONS
# ==============================================================================
hdr "4. Application Error Logs & Exceptions"

if [ -f "$DEBUG_LOG" ]; then
    DEBUG_SIZE_MB=$(du -m "$DEBUG_LOG" | awk '{print $1}')
    info "debug.log size: ${DEBUG_SIZE_MB}MB"
    if [ "$DEBUG_SIZE_MB" -gt 150 ]; then
        warn "debug.log is very large (${DEBUG_SIZE_MB}MB)! Excessive logging causes I/O disk bottlenecks."
        WARNING_ISSUES+=("debug.log is ${DEBUG_SIZE_MB}MB. Consider rotating or truncating it.")
    fi

    echo ""
    echo -e "  ${C_BOLD}Recent Exceptions / Errors in debug.log (last 10):${C_RESET}"
    grep -iE "exception|traceback|error|database is locked|timeout" "$DEBUG_LOG" 2>/dev/null | tail -10 | sed 's/^/    /' || echo "    (none)"
else
    info "debug.log does not exist or is empty."
fi

echo ""
echo -e "  ${C_BOLD}Recent Python Tracebacks from Systemd Journal (last 3 hours):${C_RESET}"
JOURNAL_ERRS=$(journalctl -u zohomap.service --since "3 hours ago" --no-pager 2>/dev/null | grep -iE "Traceback|OperationalError|Internal Server Error|Error on request" | tail -10)
if [ -n "$JOURNAL_ERRS" ]; then
    fail "Unhandled Python exceptions detected in zohomap service!"
    echo -e "${C_RED}$JOURNAL_ERRS${C_RESET}" | sed 's/^/    /'
    CRITICAL_ISSUES+=("Unhandled Python exceptions in journal log. Check journalctl -u zohomap.")
else
    ok "No unhandled Python tracebacks in recent journal logs."
fi

# ==============================================================================
#  5. DATABASE PERFORMANCE, LOCKS & LATENCY BENCHMARK
# ==============================================================================
hdr "5. Database Health & Query Latency Benchmark"

DB_URI_VAL="${DATABASE_URI:-sqlite:///database.db}"

if [[ "$DB_URI_VAL" == *"postgres"* ]]; then
    # Redact password in display output
    REDACTED_URI=$(echo "$DB_URI_VAL" | sed -E 's/(:)[^@:]+(@)/\1******\2/')
    info "Database engine: PostgreSQL ($REDACTED_URI)"
    if [ -f "$VENV_PY" ]; then
        PG_BENCH=$("$VENV_PY" -c "
import time, database, socket, ssl
from urllib.parse import urlparse

parsed = urlparse(database.DB_URI)
host = parsed.hostname
port = parsed.port or 5432

# 1. DNS Resolution
try:
    t0 = time.time()
    addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    ip = addrs[0][4][0]
    t_dns = (time.time() - t0) * 1000.0
except Exception as e:
    print(f'FAIL_DNS|{host}|{e}')
    exit(0)

# 2. Raw TCP connect
try:
    t1 = time.time()
    s = socket.create_connection((ip, port), timeout=6.0)
    s.close()
    t_tcp = (time.time() - t1) * 1000.0
except Exception as e:
    print(f'FAIL_TCP|{host}|{ip}|{port}|{e}')
    exit(0)

# 3. PostgreSQL Auth & Handshake
try:
    t2 = time.time()
    conn = database.get_db_connection()
    t_auth = (time.time() - t2) * 1000.0
except Exception as e:
    print(f'FAIL_AUTH|{ip}|{e}')
    exit(0)

# 4. Ping query (SELECT 1)
try:
    t3 = time.time()
    database.exec_query(conn, 'SELECT 1')
    t_ping = (time.time() - t3) * 1000.0
except Exception as e:
    conn.close()
    print(f'FAIL_PING|{ip}|{e}')
    exit(0)

# 5. Full count query (SELECT count(*) FROM module_records)
try:
    t4 = time.time()
    rows = database.exec_query(conn, 'SELECT count(*) as cnt FROM module_records', fetchone=True)
    t_query = (time.time() - t4) * 1000.0
    cnt = rows['cnt'] if rows else 0
    conn.close()
    print(f'OK|{ip}|{t_dns:.1f}|{t_tcp:.1f}|{t_auth:.1f}|{t_ping:.1f}|{t_query:.1f}|{cnt}')
except Exception as e:
    try: conn.close()
    except: pass
    print(f'FAIL_QUERY|{ip}|{t_tcp:.1f}|{t_auth:.1f}|{e}')
" 2>&1)
        if [[ "$PG_BENCH" == OK* ]]; then
            IFS='|' read -r _ DB_IP TDNS TTCP TAUTH TPING TQUERY RECCNT <<< "$PG_BENCH"
            ok "PostgreSQL connected ($DB_IP) | TCP: ${TTCP}ms | Auth/SSL: ${TAUTH}ms | Ping: ${TPING}ms"
            ok "Query 'SELECT count(*) FROM module_records': ${TQUERY}ms (${RECCNT} rows)"
            if (( $(echo "$TQUERY > 2000" | bc -l 2>/dev/null || echo 0) )); then
                warn "PostgreSQL query latency is slow (${TQUERY}ms). Missing indexes or high database load."
                WARNING_ISSUES+=("PostgreSQL query time (${TQUERY}ms) is high.")
            fi
        elif [[ "$PG_BENCH" == FAIL_DNS* ]]; then
            IFS='|' read -r _ DHOST DERR <<< "$PG_BENCH"
            fail "PostgreSQL DNS Resolution failed for $DHOST: $DERR"
            CRITICAL_ISSUES+=("PostgreSQL DNS resolution failure for $DHOST.")
        elif [[ "$PG_BENCH" == FAIL_TCP* ]]; then
            IFS='|' read -r _ THOST TIP TPORT TERR <<< "$PG_BENCH"
            fail "PostgreSQL TCP connection failed to $THOST ($TIP:$TPORT): $TERR"
            echo -e "${C_RED}    👉 Root Cause: AWS RDS Security Group or Network ACL is BLOCKING port $TPORT from this EC2 instance!${C_RESET}"
            echo -e "${C_YELLOW}    👉 Fix: In AWS Console -> RDS -> 'zohomap-db' -> Security Group -> Inbound Rules -> Add TCP $TPORT from this EC2 instance / subnet.${C_RESET}"
            CRITICAL_ISSUES+=("TCP to RDS blocked: $TERR (Check AWS RDS Security Group inbound rules for port $TPORT).")
        elif [[ "$PG_BENCH" == FAIL_AUTH* ]]; then
            IFS='|' read -r _ AIP AERR <<< "$PG_BENCH"
            fail "PostgreSQL Authentication/SSL failed ($AIP): $AERR"
            CRITICAL_ISSUES+=("PostgreSQL Auth/SSL error: $AERR")
        elif [[ "$PG_BENCH" == FAIL_QUERY* ]]; then
            IFS='|' read -r _ QIP QTCP QAUTH QERR <<< "$PG_BENCH"
            fail "PostgreSQL query failed ($QIP, TCP: ${QTCP}ms, Auth: ${QAUTH}ms): $QERR"
            echo -e "${C_RED}    👉 Root Cause: Database socket timeout or query lock on module_records.${C_RESET}"
            CRITICAL_ISSUES+=("PostgreSQL query failed: $QERR")
        else
            fail "PostgreSQL test failed: $PG_BENCH"
            CRITICAL_ISSUES+=("PostgreSQL test error: $PG_BENCH")
        fi
    fi
else
    info "Database engine: SQLite ($DB_FILE)"
    if [ -f "$DB_FILE" ]; then
        DB_SIZE_MB=$(du -m "$DB_FILE" | awk '{print $1}')
        info "database.db file size: ${DB_SIZE_MB}MB"

        if [ -f "$WAL_FILE" ]; then
            WAL_SIZE_MB=$(du -m "$WAL_FILE" | awk '{print $1}')
            info "database.db-wal file size: ${WAL_SIZE_MB}MB"
            if [ "$WAL_SIZE_MB" -gt 30 ]; then
                fail "CRITICAL WAL BLOAT: database.db-wal is ${WAL_SIZE_MB}MB! Uncheckpointed WAL severely degrades query performance and locks writes!"
                CRITICAL_ISSUES+=("SQLite WAL file is ${WAL_SIZE_MB}MB. Open connections are preventing WAL checkpointing, causing website freezes and timeouts.")
            elif [ "$WAL_SIZE_MB" -gt 10 ]; then
                warn "database.db-wal is elevated (${WAL_SIZE_MB}MB). Checkpointing needed."
                WARNING_ISSUES+=("SQLite WAL elevated (${WAL_SIZE_MB}MB).")
            else
                ok "SQLite WAL size is normal (${WAL_SIZE_MB}MB)."
            fi
        else
            ok "No database.db-wal file (checkpointed clean)."
        fi

        if [ -f "$VENV_PY" ]; then
            SQLITE_BENCH=$("$VENV_PY" -c "
import time, database
try:
    t0 = time.time()
    conn = database.get_db_connection()
    t_conn = (time.time() - t0) * 1000.0

    t1 = time.time()
    r1 = database.exec_query(conn, 'SELECT count(*) as cnt FROM module_records', fetchone=True)
    t_query1 = (time.time() - t1) * 1000.0

    t2 = time.time()
    r2 = database.exec_query(conn, 'SELECT count(*) as cnt FROM performance_logs', fetchone=True)
    t_query2 = (time.time() - t2) * 1000.0

    cnt1 = r1['cnt'] if r1 else 0
    cnt2 = r2['cnt'] if r2 else 0

    conn.close()
    print(f'OK|{t_conn:.1f}|{t_query1:.1f}|{cnt1}|{t_query2:.1f}|{cnt2}')
except Exception as e:
    print(f'FAIL|{e}')
" 2>&1)
            if [[ "$SQLITE_BENCH" == OK* ]]; then
                IFS='|' read -r _ TCONN TQ1 C1 TQ2 C2 <<< "$SQLITE_BENCH"
                ok "SQLite connect: ${TCONN}ms | module_records count query: ${TQ1}ms (${C1} records)"
                info "performance_logs: ${C2} rows (query: ${TQ2}ms)"

                if [ "$C2" -gt 50000 ]; then
                    warn "performance_logs table has ${C2} rows. Consider pruning older records."
                    WARNING_ISSUES+=("performance_logs has ${C2} rows.")
                fi
                if (( $(echo "$TQ1 > 1500" | bc -l 2>/dev/null || echo 0) )); then
                    warn "Database query is taking ${TQ1}ms. Under concurrent load this causes queue pileup."
                    WARNING_ISSUES+=("SQLite query latency is elevated (${TQ1}ms).")
                fi
            else
                fail "Database query benchmark failed: $SQLITE_BENCH"
                CRITICAL_ISSUES+=("Database query benchmark error: $SQLITE_BENCH")
            fi
        fi
    else
        fail "database.db not found at $DB_FILE!"
        CRITICAL_ISSUES+=("database.db missing!")
    fi
fi

# ==============================================================================
#  6. EXTERNAL NETWORK & API CONNECTIVITY
# ==============================================================================
hdr "6. External API Connectivity & Latency"

test_api_latency() {
    local target="$1"
    local name="$2"
    local res
    res=$(curl -sk -o /dev/null -w "%{http_code}|%{time_total}" --max-time 6 "$target" 2>/dev/null || echo "000|timeout")
    IFS='|' read -r code latency <<< "$res"
    if [ "$code" = "000" ] || [ "$code" = "timeout" ]; then
        fail "$name: UNREACHABLE ($target)"
        CRITICAL_ISSUES+=("Cannot reach $name ($target). Outbound network or DNS issue.")
    else
        local lat_ms
        lat_ms=$(echo "$latency * 1000" | bc 2>/dev/null | cut -d. -f1 || echo "$latency")
        ok "$name: HTTP $code in ${lat_ms}ms"
    fi
}

test_api_latency "https://www.zohoapis.com" "Zoho CRM API"
test_api_latency "https://accounts.zoho.com" "Zoho Accounts OAuth"
test_api_latency "https://maps.googleapis.com" "Google Maps API"

if [ -f "$VENV_PY" ]; then
    TOKEN_CHECK=$("$VENV_PY" -c "
import app
with app.app.app_context():
    tok = app._get_admin_access_token()
    if tok:
        print('OK')
    else:
        print('FAIL')
" 2>&1)
    if [ "$TOKEN_CHECK" = "OK" ]; then
        ok "Zoho Admin Token: Active and successfully generating access tokens."
    else
        fail "Zoho Admin Token: FAILED to generate access token! Admin logins/sync will stall."
        CRITICAL_ISSUES+=("Zoho Admin Token refresh failed. Check /api/admin/token-status.")
    fi
fi

# ==============================================================================
#  7. QUICK FIX MODE (--quick-fix)
# ==============================================================================
if [ "$1" = "--quick-fix" ] || [ "$1" = "-f" ]; then
    hdr "Executing Quick Fix Recovery..."

    echo "  [1/5] Truncating SQLite WAL if present..."
    if [ -f "$DB_FILE" ]; then
        sqlite3 "$DB_FILE" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
        ok "WAL checkpointed."
    fi

    echo "  [2/5] Truncating oversized debug.log..."
    if [ -f "$DEBUG_LOG" ] && [ "$(du -m "$DEBUG_LOG" | awk '{print $1}')" -gt 30 ]; then
        sudo truncate -s 0 "$DEBUG_LOG"
        ok "debug.log truncated."
    fi

    echo "  [3/5] Restarting zohomap service..."
    if command -v systemctl >/dev/null 2>&1; then
        systemctl restart zohomap.service 2>/dev/null || sudo systemctl restart zohomap.service
    fi
    sleep 2

    echo "  [4/5] Reloading Nginx..."
    if command -v nginx >/dev/null 2>&1; then
        (nginx -t 2>/dev/null || sudo nginx -t) && (systemctl reload nginx 2>/dev/null || sudo systemctl reload nginx)
        ok "Nginx reloaded."
    fi

    echo "  [5/5] Checking /health endpoint..."
    HEALTH_CODE=$(curl -sk -o /dev/null -w "%{http_code}" http://localhost/health 2>/dev/null || echo "000")
    if [ "$HEALTH_CODE" = "200" ]; then
        ok "App /health is responding with HTTP 200!"
    else
        warn "App /health responded with HTTP $HEALTH_CODE"
    fi
fi

# ==============================================================================
#  8. DIAGNOSTIC SUMMARY & ACTIONABLE RECOMMENDATIONS
# ==============================================================================
hdr "Diagnostic Summary & Action Plan"

echo ""
if [ ${#CRITICAL_ISSUES[@]} -gt 0 ]; then
    echo -e "${C_BOLD}${C_RED}❌ CRITICAL ISSUES DETECTED (${#CRITICAL_ISSUES[@]}):${C_RESET}"
    for issue in "${CRITICAL_ISSUES[@]}"; do
        echo -e "   ${C_RED}• $issue${C_RESET}"
    done
fi

if [ ${#WARNING_ISSUES[@]} -gt 0 ]; then
    echo ""
    echo -e "${C_BOLD}${C_YELLOW}⚠️  WARNINGS & BOTTLENECKS (${#WARNING_ISSUES[@]}):${C_RESET}"
    for warn_item in "${WARNING_ISSUES[@]}"; do
        echo -e "   ${C_YELLOW}• $warn_item${C_RESET}"
    done
fi

if [ ${#CRITICAL_ISSUES[@]} -eq 0 ] && [ ${#WARNING_ISSUES[@]} -eq 0 ]; then
    echo -e "${C_BOLD}${C_GREEN}✅ All core diagnostics passed. Server resources and services appear healthy.${C_RESET}"
fi

echo ""
echo -e "${C_BOLD}Recommended Immediate Fixes:${C_RESET}"
echo -e "  1. ${C_CYAN}One-Click Safe Recovery:${C_RESET}"
echo -e "     sudo bash $APP_DIR/diagnose_performance.sh --quick-fix"
echo ""
echo -e "  2. ${C_CYAN}Restart Gunicorn & Nginx (clears hung workers & socket locks):${C_RESET}"
echo -e "     sudo systemctl restart zohomap && sudo systemctl reload nginx"
echo ""
echo -e "  3. ${C_CYAN}If SQLite WAL was bloated:${C_RESET}"
echo -e "     sudo sqlite3 $APP_DIR/database.db 'PRAGMA wal_checkpoint(TRUNCATE); VACUUM;'"
echo ""
echo -e "  4. ${C_CYAN}Watch live Nginx gateway errors:${C_RESET}"
echo -e "     sudo tail -f /var/log/nginx/error.log"
echo ""
echo -e "  5. ${C_CYAN}Watch live Python app logs:${C_RESET}"
echo -e "     sudo journalctl -u zohomap -f"
echo ""
