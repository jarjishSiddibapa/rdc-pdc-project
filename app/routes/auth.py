"""
RDC PDC Manager — Authentication Routes
"""
import re
import time
import threading
from app.utils import now_ist
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, csrf
from app.models.user import User
from app.services.audit_service import log_action

bp = Blueprint('auth', __name__)

# ── Simple in-memory brute-force guard ───────────────────────────────────────
# Tracks failed login attempts per IP. No external dependency needed.
_RATE_LIMIT_LOCK     = threading.Lock()
_failed_attempts: dict[str, list[float]] = {}   # ip → [timestamp, ...]
_MAX_ATTEMPTS   = 10          # max failures before lockout
_WINDOW_SECONDS = 300         # rolling 5-minute window
_LOCKOUT_SECONDS = 600        # 10-minute lockout after threshold


def _get_client_ip() -> str:
    """Return the real client IP, respecting X-Forwarded-For if set."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'


def _is_rate_limited(ip: str) -> tuple[bool, int]:
    """
    Return (is_locked, seconds_remaining).
    Cleans up old entries on every call.
    """
    now = time.monotonic()
    with _RATE_LIMIT_LOCK:
        attempts = _failed_attempts.get(ip, [])
        # Keep only attempts within the window
        attempts = [t for t in attempts if now - t < _WINDOW_SECONDS]
        _failed_attempts[ip] = attempts
        if len(attempts) >= _MAX_ATTEMPTS:
            oldest_in_window = attempts[0]
            remaining = int(_LOCKOUT_SECONDS - (now - oldest_in_window))
            if remaining > 0:
                return True, remaining
            # Lockout expired — clear
            _failed_attempts[ip] = []
        return False, 0


def _record_failure(ip: str) -> None:
    now = time.monotonic()
    with _RATE_LIMIT_LOCK:
        _failed_attempts.setdefault(ip, []).append(now)


def _clear_failures(ip: str) -> None:
    with _RATE_LIMIT_LOCK:
        _failed_attempts.pop(ip, None)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        ip = _get_client_ip()

        # ── Rate-limit check ──────────────────────────────────────────────
        locked, remaining = _is_rate_limited(ip)
        if locked:
            mins = remaining // 60
            secs = remaining % 60
            wait = f'{mins}m {secs}s' if mins else f'{secs}s'
            flash(f'Too many failed attempts. Please wait {wait} before trying again.', 'danger')
            return render_template('auth/login.html')

        login_id = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Accept either username or email
        user = (User.query.filter_by(username=login_id).first()
                or User.query.filter_by(email=login_id).first())

        if user is None or not user.check_password(password):
            _record_failure(ip)
            # Audit failed attempts (only log the identifier, never password)
            log_action('users', None, 'LOGIN_FAILED',
                       description=f"Failed login attempt for '{login_id}' from {ip}")
            flash('Invalid username/email or password.', 'danger')
            return render_template('auth/login.html')

        if not user.is_active:
            _record_failure(ip)
            flash('Your account has been deactivated. Contact admin.', 'danger')
            return render_template('auth/login.html')

        # Successful login — clear any recorded failures for this IP
        _clear_failures(ip)
        # Session-fixation protection: destroy the pre-auth session so a new
        # session ID is issued on login. Without this, an attacker who planted
        # a known session cookie before login could reuse it post-login.
        session.clear()
        # Never use persistent remember-me cookies; session expires on inactivity
        login_user(user, remember=False)
        session['_last_active'] = now_ist().timestamp()
        user.last_login = now_ist()
        db.session.commit()

        log_action('users', user.user_id, 'LOGIN',
                   description=f"User '{user.username}' logged in from {ip}")

        # Safe redirect — only allow relative next URLs to prevent open redirect
        next_page = request.args.get('next')
        if next_page and next_page.startswith('/') and not next_page.startswith('//'):
            return redirect(next_page)
        return redirect(url_for('dashboard.index'))

    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
    log_action('users', current_user.user_id, 'LOGOUT',
               description=f"User '{current_user.username}' logged out")
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/logout-beacon', methods=['POST'])
@csrf.exempt   # navigator.sendBeacon cannot include a CSRF token
def logout_beacon():
    """Called by sendBeacon on tab close. Logs the user out silently."""
    if current_user.is_authenticated:
        log_action('users', current_user.user_id, 'LOGOUT',
                   description=f"User '{current_user.username}' session ended (tab closed)")
        logout_user()
        session.clear()
    return '', 204


@bp.route('/heartbeat')
@login_required
def heartbeat():
    """Ping endpoint — keeps server-side _last_active timestamp fresh."""
    session['_last_active'] = now_ist().timestamp()
    return jsonify(ok=True)


# ── Forgot-password rate limiter (separate from login) ────────────────────────
_FP_LOCK                              = threading.Lock()
_fp_attempts: dict[str, list[float]] = {}   # ip → [timestamp, ...]
_FP_MAX_PER_WINDOW                   = 3    # max requests per window
_FP_WINDOW                           = 900  # 15-minute window


def _fp_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    with _FP_LOCK:
        hits = [t for t in _fp_attempts.get(ip, []) if now - t < _FP_WINDOW]
        _fp_attempts[ip] = hits
        if len(hits) >= _FP_MAX_PER_WINDOW:
            return True
        hits.append(now)
        _fp_attempts[ip] = hits
        return False


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        ip = _get_client_ip()

        if _fp_rate_limited(ip):
            flash('Too many requests. Please wait 15 minutes before trying again.', 'danger')
            return render_template('auth/forgot_password.html')

        email = request.form.get('email', '').strip().lower()

        # Always show the same message to prevent email enumeration
        flash('If that email address is registered and active, '
              'you will receive a password reset link within a few minutes.', 'success')

        if email:
            user = User.query.filter(
                db.func.lower(User.email) == email
            ).first()

            if user and user.is_active and user.email:
                from app.models.password_reset import PasswordResetToken
                from app.services.email_service import send_email, get_email_config

                if get_email_config():
                    token    = PasswordResetToken.generate_for(user)
                    reset_url = url_for('auth.reset_password', token=token, _external=True)
                    send_email(
                        user.email,
                        'RDC PDC — Password Reset Request',
                        _reset_email_html(user, reset_url),
                    )
                    log_action('users', user.user_id, 'PASSWORD_RESET_REQUESTED',
                               description=f"Password reset link sent to '{user.email}'")

        return redirect(url_for('auth.forgot_password'))

    return render_template('auth/forgot_password.html')


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    from app.models.password_reset import PasswordResetToken

    # Validate token on every visit
    record, error = PasswordResetToken.verify(token)
    if error:
        flash(error, 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        new_pw     = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')

        if new_pw != confirm_pw:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset_password.html', token=token)

        # Same strength rules as user creation
        errs = []
        if len(new_pw) < 8:                          errs.append('at least 8 characters')
        if not re.search(r'[A-Z]', new_pw):          errs.append('an uppercase letter')
        if not re.search(r'[a-z]', new_pw):          errs.append('a lowercase letter')
        if not re.search(r'\d', new_pw):             errs.append('a digit')
        if not re.search(r'[^A-Za-z0-9]', new_pw):  errs.append('a special character')
        if errs:
            flash('Password must contain: ' + ', '.join(errs) + '.', 'danger')
            return render_template('auth/reset_password.html', token=token)

        user = record.user
        user.set_password(new_pw)
        user.updated_at = now_ist()
        # Commit the password change first, independently of the token burn.
        # This prevents a subtle SQLAlchemy session-identity issue where the
        # user object's dirty state might not be flushed inside consume().
        db.session.commit()
        record.consume()

        log_action('users', user.user_id, 'PASSWORD_RESET',
                   description=f"Password reset via email link for '{user.username}'")

        flash('Password reset successfully! Please sign in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


def _reset_email_html(user, reset_url):
    """HTML body for the password-reset email."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0e1a;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0e1a;">
<tr><td align="center" style="padding:48px 20px;">

  <table width="580" cellpadding="0" cellspacing="0"
         style="background:#111827;border-radius:16px;border:1px solid rgba(51,65,85,0.6);overflow:hidden;max-width:580px;">

    <!-- Header gradient -->
    <tr><td style="background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);padding:36px 40px;text-align:center;">
      <div style="width:56px;height:56px;background:rgba(255,255,255,0.15);border-radius:50%;
                  display:inline-flex;align-items:center;justify-content:center;margin-bottom:14px;">
        <span style="font-size:26px;line-height:1;">🔐</span>
      </div>
      <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">
        Password Reset Request
      </h1>
      <p style="margin:8px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">RDC PDC Manager</p>
    </td></tr>

    <!-- Body -->
    <tr><td style="padding:36px 40px 28px;">
      <p style="margin:0 0 18px;color:#94a3b8;font-size:14px;line-height:1.7;">
        Hi <strong style="color:#f1f5f9;">{user.full_name}</strong>,
      </p>
      <p style="margin:0 0 28px;color:#94a3b8;font-size:14px;line-height:1.7;">
        We received a request to reset the password for your account
        (<strong style="color:#f1f5f9;">{user.username}</strong>).
        Click the button below to choose a new password.
        This link is valid for <strong style="color:#f1f5f9;">1 hour</strong> and can only be used once.
      </p>

      <!-- CTA button -->
      <div style="text-align:center;margin:32px 0;">
        <a href="{reset_url}"
           style="display:inline-block;background:linear-gradient(135deg,#6366f1,#8b5cf6);
                  color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;
                  padding:15px 40px;border-radius:10px;letter-spacing:0.2px;
                  box-shadow:0 6px 20px rgba(99,102,241,0.4);">
          Reset My Password &nbsp;→
        </a>
      </div>

      <p style="margin:0 0 6px;color:#475569;font-size:12px;">Or copy this link into your browser:</p>
      <p style="margin:0 0 28px;word-break:break-all;">
        <a href="{reset_url}" style="color:#818cf8;font-size:12px;text-decoration:none;">{reset_url}</a>
      </p>

      <!-- Warning box -->
      <div style="background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.35);
                  border-radius:10px;padding:16px 18px;">
        <p style="margin:0;color:#f59e0b;font-size:13px;line-height:1.6;">
          <strong>⚠ Didn't request this?</strong><br>
          If you did not request a password reset, no action is needed —
          your password will remain unchanged. You may want to review your account security.
        </p>
      </div>
    </td></tr>

    <!-- Footer -->
    <tr><td style="padding:20px 40px 28px;border-top:1px solid rgba(51,65,85,0.4);text-align:center;">
      <p style="margin:0;color:#334155;font-size:11px;line-height:1.6;">
        This is an automated message from RDC PDC Manager.<br>
        Powered by <strong style="color:#475569;">RDC IT Team</strong>
      </p>
    </td></tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')

        if not current_user.check_password(current_pw):
            flash('Current password is incorrect.', 'danger')
            return render_template('auth/change_password.html')

        if len(new_pw) < 8:
            flash('New password must be at least 8 characters long.', 'danger')
            return render_template('auth/change_password.html')

        if new_pw != confirm_pw:
            flash('New passwords do not match.', 'danger')
            return render_template('auth/change_password.html')

        if current_pw == new_pw:
            flash('New password must be different from current password.', 'warning')
            return render_template('auth/change_password.html')

        current_user.set_password(new_pw)
        current_user.updated_at = now_ist()
        db.session.commit()

        log_action('users', current_user.user_id, 'UPDATE',
                   description=f"User '{current_user.username}' changed password")

        flash('Password changed successfully!', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('auth/change_password.html')
