#!/bin/bash
# MistWANPerformance - Container Entrypoint Script
#
# Provides:
#   - Crash detection and logging
#   - Automatic restart on failure
#   - Graceful shutdown handling
#   - Startup health verification
#
# The script monitors the Python dashboard process and restarts it
# if it crashes, while logging crash information for debugging.

set -e

# Configuration
MAX_RESTARTS=10
RESTART_DELAY=5
CRASH_LOG="/app/data/logs/crash.log"
STARTUP_TIMEOUT=60

# Track restart count
RESTART_COUNT=0

# Ensure log directory exists
mkdir -p /app/data/logs

# Log function with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$CRASH_LOG"
}

# Handle graceful shutdown
cleanup() {
    log "[SHUTDOWN] Received termination signal, shutting down gracefully..."
    if [ -n "$DASHBOARD_PID" ] && kill -0 "$DASHBOARD_PID" 2>/dev/null; then
        kill -TERM "$DASHBOARD_PID"
        wait "$DASHBOARD_PID" 2>/dev/null || true
    fi
    log "[SHUTDOWN] Shutdown complete"
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT SIGQUIT

# Log startup
log "============================================================"
log "[STARTUP] MistWANPerformance Container Starting"
log "[STARTUP] Python: $(python --version 2>&1)"
log "[STARTUP] Max restarts: $MAX_RESTARTS"
log "[STARTUP] Restart delay: ${RESTART_DELAY}s"
log "============================================================"

# Main restart loop
while true; do
    log "[START] Starting dashboard process (attempt $((RESTART_COUNT + 1)))"
    
    # Start the dashboard in background
    python run_dashboard.py &
    DASHBOARD_PID=$!
    
    log "[START] Dashboard PID: $DASHBOARD_PID"
    
    # Wait for process to exit
    wait $DASHBOARD_PID
    EXIT_CODE=$?
    
    # Process exited
    if [ $EXIT_CODE -eq 0 ]; then
        log "[EXIT] Dashboard exited normally (code 0)"
        break
    fi
    
    # Crash detected
    RESTART_COUNT=$((RESTART_COUNT + 1))
    log "[CRASH] Dashboard crashed with exit code $EXIT_CODE"
    log "[CRASH] Restart count: $RESTART_COUNT / $MAX_RESTARTS"
    
    # Log system state at crash
    log "[DEBUG] Memory usage:"
    cat /proc/meminfo | grep -E "MemTotal|MemFree|MemAvailable" >> "$CRASH_LOG" 2>/dev/null || true
    
    # Check restart limit
    if [ $RESTART_COUNT -ge $MAX_RESTARTS ]; then
        log "[FATAL] Maximum restart count ($MAX_RESTARTS) reached, giving up"
        log "[FATAL] Check logs for root cause: $CRASH_LOG"
        exit 1
    fi
    
    # Wait before restart
    log "[RESTART] Waiting ${RESTART_DELAY}s before restart..."
    sleep $RESTART_DELAY
    
    # Increase delay with each restart (backoff)
    RESTART_DELAY=$((RESTART_DELAY + 5))
    if [ $RESTART_DELAY -gt 60 ]; then
        RESTART_DELAY=60
    fi
done

log "[EXIT] Entrypoint script exiting"
