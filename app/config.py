"""
RDC PDC Manager — Application Configuration
"""
import os
import logging
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

_log = logging.getLogger(__name__)

_SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not _SECRET_KEY:
    _SECRET_KEY = 'dev-fallback-key-change-me'
    _log.warning(
        "SECRET_KEY is not set in the environment. "
        "Using an insecure development fallback — do NOT use this in production."
    )

_DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is required but not set. "
        "Add it to your .env file: "
        "DATABASE_URL=mysql+mysqlconnector://user:pass@host/dbname"
    )


class Config:
    """Base configuration."""
    SECRET_KEY = _SECRET_KEY

    # MySQL Database — uses mysqlconnector (same driver as sibling projects on this machine)
    SQLALCHEMY_DATABASE_URI = _DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20,
    }

    # Session
    # 10-minute server-side inactivity timeout — enforced both server and client side.
    SESSION_TIMEOUT_MINUTES    = 10
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    # Refresh the expiry timestamp on every request so active users stay logged in
    SESSION_REFRESH_EACH_REQUEST = True
    SESSION_COOKIE_HTTPONLY  = True
    SESSION_COOKIE_SAMESITE  = 'Lax'
    # True in production (HTTPS); False for local dev without TLS
    SESSION_COOKIE_SECURE    = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    # Never use persistent "Remember Me" cookies — session must expire on inactivity
    REMEMBER_COOKIE_DURATION = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE   = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'

    # CSRF token has no independent time limit — session expiry handles security.
    # A fixed time limit causes form failures for users who stay on a page longer
    # than the limit even when the session is still alive (kept by heartbeat).
    WTF_CSRF_TIME_LIMIT = None

    # Uploads
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join('app', 'static', 'uploads'))
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'gif', 'webp'}

    # ── Server-side sessions (Flask-Session + filesystem backend) ──
    # Stores session data as files so beacon-triggered logout is truly
    # immediate — the session file is deleted/cleared on the server and
    # the client's session-ID cookie becomes worthless even within 10 min.
    # Filesystem is the most compatible backend: no DB table ordering
    # issues, no serialisation conflicts with Flask-WTF CSRF tokens.
    SESSION_TYPE              = 'filesystem'
    SESSION_FILE_DIR          = os.path.join(
                                    os.path.dirname(os.path.abspath(__file__)),
                                    '..', 'flask_sessions')
    SESSION_FILE_THRESHOLD    = 500    # max session files before oldest purged
    SESSION_PERMANENT         = True   # respects PERMANENT_SESSION_LIFETIME
    # SESSION_USE_SIGNER intentionally omitted — Flask-Session 0.8 signs
    # sessions internally; enabling it externally double-signs the ID and
    # causes cachelib to look up the wrong filename on subsequent requests,
    # producing a fresh empty session (and CSRF token missing errors).

    # ── URL ID Obfuscation (hashids) ────────────────────────────────
    # HASHID_SALT must be set in .env for production.
    # A publicly-known salt allows reversing hashids to enumerate DB IDs.
    _hashid_salt = os.environ.get('HASHID_SALT', '')
    if not _hashid_salt:
        _hashid_salt = 'rdc-pdc-X7k9mN2pQ5wR8vL3jH6sY1tA4cE0uF'
        _log.warning(
            "HASHID_SALT is not set. Using the default public salt — "
            "set HASHID_SALT in your .env for production."
        )
    HASHID_SALT = _hashid_salt
    HASHID_MIN_LENGTH = 8   # minimum length of encoded strings

    # Application
    APP_NAME = 'RDC PDC Manager'
    ITEMS_PER_PAGE = 20

    # Oracle ERP R12.2.10 — Direct DB connection (oracledb thick mode)
    ERP_DB_HOST          = os.environ.get('ERP_DB_HOST', '')
    ERP_DB_PORT          = os.environ.get('ERP_DB_PORT', '1521')
    ERP_DB_SERVICE       = os.environ.get('ERP_DB_SERVICE', '')
    ERP_DB_USERNAME      = os.environ.get('ERP_DB_USERNAME', '')
    ERP_DB_PASSWORD      = os.environ.get('ERP_DB_PASSWORD', '')
    ERP_INSTANT_CLIENT   = os.environ.get('ERP_INSTANT_CLIENT', r'C:\oracle\instantclient')
