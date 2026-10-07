"""
Gunicorn configuration for RDC PDC Manager (production).

Usage:
    gunicorn -c gunicorn.conf.py "app:create_app()"
"""
import multiprocessing
import os

# ── Binding ──────────────────────────────────────────────────────────────────
bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8000')

# ── Workers ───────────────────────────────────────────────────────────────────
# 2–4 × CPU cores is a common starting point for I/O-bound Flask apps.
workers = int(os.environ.get('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))
worker_class = 'sync'          # use 'gevent' if you add async I/O later
threads = 2                    # sync workers + threads = simple concurrency

# ── Timeouts ─────────────────────────────────────────────────────────────────
timeout = 60                   # kill workers that take > 60 s (long ERP syncs excluded)
keepalive = 5                  # seconds to wait for next request on a keep-alive connection
graceful_timeout = 30          # seconds to finish in-flight requests on SIGTERM

# ── Logging ──────────────────────────────────────────────────────────────────
accesslog = os.environ.get('GUNICORN_ACCESS_LOG', '-')   # '-' → stdout
errorlog  = os.environ.get('GUNICORN_ERROR_LOG',  '-')   # '-' → stderr
loglevel  = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" in %(D)sµs'

# ── Security ─────────────────────────────────────────────────────────────────
limit_request_line   = 4096   # max bytes in request line
limit_request_fields = 100    # max number of request headers
forwarded_allow_ips  = os.environ.get('GUNICORN_FORWARDED_IPS', '127.0.0.1')

# ── Process naming ───────────────────────────────────────────────────────────
proc_name = 'rdc-pdc-manager'

# ── Hooks ────────────────────────────────────────────────────────────────────
def on_starting(server):
    server.log.info("RDC PDC Manager starting up")

def worker_exit(server, worker):
    server.log.info("Worker %s exited", worker.pid)
