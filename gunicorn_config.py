"""
Gunicorn configuration for MistWANPerformance Dashboard.

This configuration optimizes the dashboard for handling concurrent requests
without blocking on heavy operations.
"""

import os
import multiprocessing

# Server socket
bind = f"0.0.0.0:{os.getenv('DASH_PORT', '8050')}"
backlog = 2048

# Worker processes
# MEMORY-OPTIMIZED: Single worker with many threads
# Each worker loads ~1GB of cached data, so multiple workers exceed memory limits
# Single worker with 8 threads handles concurrent requests without duplicating memory
workers = 1
worker_class = 'gthread'  # Threaded workers for better concurrency
threads = 8  # More threads per worker for concurrent request handling

# Worker timeout
timeout = 120  # Allow longer requests (SLE detail views can be slow)
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = '-'  # Log to stdout
errorlog = '-'   # Log to stderr
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'mistwan-dashboard'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Preload app for memory efficiency via copy-on-write
# With single worker, this doesn't matter much but keeps startup clean
preload_app = True

# Memory management
# Higher max_requests since we have only 1 worker
max_requests = 5000  # Restart worker after N requests (prevent memory leaks)
max_requests_jitter = 200  # Add randomness to restarts

# Debugging
reload = False  # Don't auto-reload in production
check_config = False


def on_starting(server):
    """Called just before the master process is initialized."""
    print("[GUNICORN] Starting MistWANPerformance Dashboard")


def on_reload(server):
    """Called to recycle workers during a reload."""
    print("[GUNICORN] Reloading workers")


def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    print(f"[GUNICORN] Worker {worker.pid} interrupted")


def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    print(f"[GUNICORN] Worker {worker.pid} aborted")
