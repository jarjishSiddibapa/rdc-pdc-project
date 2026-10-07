"""
RDC PDC Manager — Application Factory
"""
import os
import uuid
import logging
from app.utils import now_ist
from flask import Flask, render_template, session, redirect, url_for, flash, request, jsonify
from app.config import Config
from app.extensions import db, login_manager, csrf, migrate, server_session, scheduler
from app.hashids_helper import init_hashids, hid_encode, HashIDConverter

log = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ── Proxy trust (Nginx / Apache in production) ───────────────────
    # Trusts exactly one hop of X-Forwarded-For / X-Forwarded-Proto so
    # request.remote_addr and request.scheme are correct behind a reverse
    # proxy. Prevents IP-spoofing by untrusted clients (only the last
    # proxy hop is trusted, not client-supplied headers directly).
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # ── Initialise hashids BEFORE anything touches url_for ───────────
    init_hashids(
        salt=app.config['HASHID_SALT'],
        min_length=app.config.get('HASHID_MIN_LENGTH', 8),
    )
    app.url_map.converters['hashid'] = HashIDConverter

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    # ── Server-side sessions (filesystem — no DB dependency) ────────
    import os as _os
    _os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    server_session.init_app(app)

    # User loader for Flask-Login
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        if user and user.is_active:
            return user
        return None

    # Register blueprints
    from app.routes.auth import bp as auth_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.cheques import bp as cheques_bp
    from app.routes.customers import bp as customers_bp
    from app.routes.deposits import bp as deposits_bp
    from app.routes.reconciliation import bp as reconciliation_bp
    from app.routes.resolution import bp as resolution_bp
    from app.routes.admin import bp as admin_bp
    from app.routes.notifications import bp as notifications_bp
    from app.routes.reports import bp as reports_bp
    from app.routes.erp_sync import bp as erp_sync_bp
    from app.routes.profile import bp as profile_bp
    from app.routes.public import bp as public_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(cheques_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(deposits_bp)
    app.register_blueprint(reconciliation_bp)
    app.register_blueprint(resolution_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(erp_sync_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(public_bp)

    # Ensure upload directory exists
    upload_path = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(upload_path, exist_ok=True)

    # Context processors (available in all templates)
    @app.context_processor
    def inject_globals():
        return {
            'app_name': app.config.get('APP_NAME', 'RDC PDC Manager'),
            'current_year': now_ist().year,
            'hid': hid_encode,   # {{ hid(some_id) }} in templates → encoded string
        }

    # ── Server-side session inactivity enforcement ──────────────────
    # Endpoints that must be reachable even after session expiry
    _OPEN_ENDPOINTS = {'auth.login', 'auth.logout', 'auth.logout_beacon',
                       'auth.heartbeat', 'auth.forgot_password',
                       'auth.reset_password', 'public.view_cheque',
                       'public.view_cheque_file', 'health_check', 'static'}

    @app.before_request
    def enforce_session_timeout():
        from flask_login import current_user, logout_user
        # Skip public / auth endpoints
        if request.endpoint in _OPEN_ENDPOINTS:
            return None
        if current_user.is_authenticated:
            last = session.get('_last_active')
            now_ts = now_ist().timestamp()
            timeout = app.config['PERMANENT_SESSION_LIFETIME'].total_seconds()
            if last and (now_ts - last) > timeout:
                logout_user()
                session.clear()
                flash('Your session expired due to inactivity. Please log in again.',
                      'warning')
                return redirect(url_for('auth.login'))
            # Update last-active timestamp on every authenticated request
            session['_last_active'] = now_ts

    # ── Security headers on every response ─────────────────────────
    @app.after_request
    def set_security_headers(response):
        # Prevent MIME-type sniffing
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        # Block clickjacking — only same origin can iframe this app
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        # Strict referrer for cross-origin requests (hides URL in Referer header)
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        # Disable access to sensitive browser APIs from this origin
        response.headers.setdefault(
            'Permissions-Policy',
            'geolocation=(), camera=(), microphone=(), payment=()'
        )
        # Content-Security-Policy — blocks external script/style injection.
        # unsafe-inline is required because the app uses inline <script> and
        # <style> tags throughout. A nonce-based CSP would be the next upgrade.
        # jsdelivr.net is whitelisted for Tom Select (CDN-hosted UI library).
        if 'text/html' in response.content_type:
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: blob:; "   # data: for avatars, blob: for file previews
                "font-src 'self' https://cdn.jsdelivr.net; "
                "connect-src 'self'; "
                "frame-src 'self' blob:; "        # blob: for PDF embeds
                "object-src 'self' blob:; "       # PDF <embed> tags
                "base-uri 'self'; "
                "form-action 'self';"
            )
            response.headers.setdefault('Content-Security-Policy', csp)
        # HSTS — only activate when TLS is confirmed (SESSION_COOKIE_SECURE=true)
        if app.config.get('SESSION_COOKIE_SECURE'):
            response.headers.setdefault(
                'Strict-Transport-Security',
                'max-age=31536000; includeSubDomains; preload'
            )
        # Disable browser caching of authenticated pages
        if response.status_code == 200 and 'text/html' in response.content_type:
            response.headers.setdefault('Cache-Control', 'no-store, private')
        return response

    # Error handlers
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template('errors/405.html'), 405

    @app.errorhandler(413)
    def request_entity_too_large(e):
        return render_template('errors/413.html'), 413

    @app.errorhandler(429)
    def too_many_requests(e):
        retry_after = getattr(e, 'retry_after', None)
        return render_template('errors/429.html', retry_after=retry_after), 429

    @app.errorhandler(500)
    def server_error(e):
        error_ref = uuid.uuid4().hex[:12].upper()
        log.error('500 error [ref=%s]: %s', error_ref, e, exc_info=True)
        return render_template('errors/500.html', error_ref=error_ref), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        error_ref = uuid.uuid4().hex[:12].upper()
        log.exception('Unhandled exception [ref=%s]', error_ref)
        return render_template('errors/500.html', error_ref=error_ref), 500

    # Health-check endpoint — no auth required, no session touch
    @app.route('/health')
    def health_check():
        try:
            db.session.execute(db.text('SELECT 1'))
            return jsonify(status='ok', db='ok'), 200
        except Exception as exc:  # pragma: no cover
            log.error('Health check DB failure: %s', exc)
            return jsonify(status='error', db='unreachable'), 503

    # Create tables and seed admin
    with app.app_context():
        from app.models import (User, Customer, Cheque, ChequeStatusHistory,
                                ChequeDeposit, Reconciliation, ChequeResolution,
                                Notification, AuditLog, Bank, EmailConfig,
                                ERPSyncSchedule, PasswordResetToken, ChequeShareToken)
        db.create_all()
        _seed_admin(db)

    # ── Scheduled jobs ──────────────────────────────────────────
    _register_scheduler(app)

    return app


def _erp_sync_job(app):
    """Scheduled ERP sync — customers + salesreps from Oracle ERP."""
    with app.app_context():
        from app.services import erp_service
        if not erp_service.is_configured():
            log.info('[Scheduler] ERP not configured — skipping sync.')
            return
        try:
            result = erp_service.sync_from_erp(created_by=None)
            log.info(
                '[Scheduler] ERP sync done — '
                'customers: +%d / ~%d | salesreps: +%d / ~%d | errors: %d',
                result['cust_created'], result['cust_updated'],
                result['user_created'], result['user_updated'],
                len(result['errors']),
            )
            if result['errors']:
                for e in result['errors']:
                    log.warning('[Scheduler] ERP sync error: %s', e)
            # Audit log for scheduled run (no user_id — system action)
            from app.services.audit_service import log_action as _log
            from app.models.audit import AuditLog
            from app.extensions import db as _db
            entry = AuditLog(
                table_name='erp_sync',
                record_id=None,
                action='ERP_SYNC',
                description=(
                    f"Scheduled ERP sync: "
                    f"{result['cust_created']} customers created, "
                    f"{result['cust_updated']} updated, "
                    f"{result['user_created']} salesreps created"
                ),
                user_id=None,
                ip_address='scheduler',
            )
            _db.session.add(entry)
            _db.session.commit()
        except erp_service.ERPConnectionError as e:
            log.error('[Scheduler] ERP connection failed: %s', e)
        except Exception as e:
            log.exception('[Scheduler] Unexpected error during ERP sync: %s', e)


def reload_erp_schedules(app):
    """
    Public API — remove all existing ERP sync jobs and re-register
    from the erp_sync_schedules table. Call this after any schedule change.
    """
    # Remove existing ERP sync jobs
    for job in scheduler.get_jobs():
        if job.id.startswith('erp_sync_'):
            try:
                scheduler.remove_job(job.id)
            except Exception:
                pass

    # Re-add from DB
    with app.app_context():
        from app.models.erp_schedule import ERPSyncSchedule
        schedules = ERPSyncSchedule.query.filter_by(is_active='Y').all()
        for s in schedules:
            scheduler.add_job(
                func=_erp_sync_job,
                args=[app],
                trigger='cron',
                hour=s.hour,
                minute=s.minute,
                id=f'erp_sync_{s.schedule_id}',
                name=f'ERP Sync {s.time_display} IST{(" — " + s.label) if s.label else ""}',
                replace_existing=True,
                misfire_grace_time=3600,
            )
        count = len(schedules)
        if count:
            log.info('[Scheduler] %d ERP sync schedule(s) loaded.', count)
        else:
            log.info('[Scheduler] No ERP sync schedules configured.')


def _register_scheduler(app):
    """Start the APScheduler and load DB-configured ERP sync schedules.
    Guards against double-start in Flask debug reloader (Werkzeug forks a child).
    """
    import os
    if scheduler.running:
        return
    # In debug mode skip the parent watcher process
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
        return

    scheduler.start()
    log.info('[Scheduler] Started.')

    # Seed a default 18:00 IST schedule if none exist
    with app.app_context():
        from app.models.erp_schedule import ERPSyncSchedule
        if ERPSyncSchedule.query.count() == 0:
            from app.extensions import db as _db
            default = ERPSyncSchedule(hour=18, minute=0,
                                      label='Default (6 PM IST)')
            _db.session.add(default)
            _db.session.commit()
            log.info('[Scheduler] Seeded default 18:00 IST ERP sync schedule.')

    reload_erp_schedules(app)


def _seed_admin(db):
    """Seed the default admin user if doesn't exist."""
    from app.models.user import User

    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            full_name='System Administrator',
            role='Admin',
            email='admin@rdcpdc.local',
            avatar_color='#6366f1',
            created_at=now_ist(),
        )
        seed_pw = os.environ.get('ADMIN_SEED_PASSWORD', 'ChangeMe@FirstLogin!')
        admin.set_password(seed_pw)
        db.session.add(admin)
        db.session.commit()
        log.info("[SEED] Default admin user created. Username: admin (password from ADMIN_SEED_PASSWORD env)")
