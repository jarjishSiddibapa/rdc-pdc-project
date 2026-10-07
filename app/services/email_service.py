"""
RDC PDC Manager — Email Service
Handles sending email notifications using admin-configured SMTP settings.
Uses Fernet encryption for storing SMTP passwords securely.
All outbound emails are sent in a background thread so they never block
the HTTP request cycle (SMTP can take up to 10 s per connection).
"""
import base64
import hashlib
import logging
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from cryptography.fernet import Fernet
from flask import current_app

from app.extensions import db
from app.models.settings import EmailConfig

log = logging.getLogger(__name__)


def _get_fernet(secret_key):
    """Derive a Fernet key from the Flask SECRET_KEY."""
    digest = hashlib.sha256(secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_password(password):
    """Encrypt a password using the app's secret key."""
    f = _get_fernet(current_app.config['SECRET_KEY'])
    return f.encrypt(password.encode()).decode()


def decrypt_password(encrypted_password):
    """Decrypt a password using the app's secret key."""
    f = _get_fernet(current_app.config['SECRET_KEY'])
    return f.decrypt(encrypted_password.encode()).decode()


def get_email_config():
    """Get the active email configuration."""
    return EmailConfig.query.filter_by(is_active='Y').first()


def _send_smtp(to_email, subject, html_body, config_snapshot):
    """
    Internal blocking SMTP send — runs inside a background thread.
    `config_snapshot` is a plain dict so the thread needs no DB access.
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = f"{config_snapshot['sender_name']} <{config_snapshot['sender_email']}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(config_snapshot['smtp_server'],
                          config_snapshot['smtp_port'], timeout=15) as server:
            if config_snapshot['tls_enabled']:
                server.starttls()
            server.login(config_snapshot['smtp_username'],
                         config_snapshot['smtp_password_plain'])
            server.send_message(msg)

    except smtplib.SMTPAuthenticationError:
        log.error("Email to %s failed: SMTP authentication error", to_email)
    except smtplib.SMTPConnectError:
        log.error("Email to %s failed: could not connect to SMTP server", to_email)
    except Exception as e:
        log.error("Email to %s failed: %s", to_email, e, exc_info=True)


def send_email(to_email, subject, html_body):
    """
    Send an email asynchronously (fire-and-forget background thread).
    Returns immediately — the caller is never blocked by SMTP latency.

    Returns:
        tuple: (queued: bool, error_message: str or None)
    """
    config = get_email_config()
    if not config:
        return False, "Email not configured"

    try:
        # Snapshot config values into a plain dict so the thread doesn't need
        # a DB session or Flask app context after this point.
        config_snapshot = {
            'sender_name':       config.sender_name,
            'sender_email':      config.sender_email,
            'smtp_server':       config.smtp_server,
            'smtp_port':         config.smtp_port,
            'tls_enabled':       config.tls_enabled,
            'smtp_username':     config.smtp_username,
            'smtp_password_plain': decrypt_password(config.smtp_password_encrypted),
        }
    except Exception as e:
        log.error("Failed to prepare email config for %s: %s", to_email, e)
        return False, str(e)

    t = threading.Thread(
        target=_send_smtp,
        args=(to_email, subject, html_body, config_snapshot),
        daemon=True,
        name=f"email-{to_email[:20]}",
    )
    t.start()
    return True, None


def test_email_connection(smtp_server, smtp_port, smtp_username, smtp_password, use_tls=True):
    """
    Test SMTP connection synchronously (used only from the admin settings UI).

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            if use_tls:
                server.starttls()
            server.login(smtp_username, smtp_password)
        return True, None
    except Exception as e:
        return False, str(e)
