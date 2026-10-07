"""
RDC PDC Manager — ERP Sync Routes
Admin-only: sync customers/salesreps from Oracle ERP R12.2.10,
and manage the DB-persisted sync schedule.
"""
import threading
from datetime import datetime
from app.utils import now_ist
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import current_user
from app.extensions import db, scheduler
from app.models.user import User
from app.models.customer import Customer
from app.models.erp_schedule import ERPSyncSchedule
from app.services import erp_service
from app.services.audit_service import log_action
from app.decorators import admin_required

bp = Blueprint('erp_sync', __name__, url_prefix='/erp-sync')

# Simple in-memory state for the background sync job
_sync_status = {
    'running': False, 'result': None, 'error': None,
    'started_at': None, 'logs': [],
    'progress': {
        'users_total': 0, 'users_done': 0,
        'customers_total': 0, 'customers_done': 0,
    },
}

_MAX_LOGS = 500   # cap in-memory log lines to avoid unbounded growth


def _reload_schedules():
    """Reload APScheduler jobs from DB (import lazily to avoid circular imports)."""
    from app import reload_erp_schedules
    from flask import current_app
    reload_erp_schedules(current_app._get_current_object())


# ── Dashboard ─────────────────────────────────────────────────────────────────

@bp.route('/')
@admin_required
def index():
    sales_users = User.query.filter_by(role='Sales').order_by(User.full_name).all()
    total_custs = Customer.query.filter_by(is_active='Y').count()
    erp_custs   = Customer.query.filter(
        Customer.erp_customer_id.isnot(None), Customer.is_active == 'Y'
    ).count()
    schedules   = ERPSyncSchedule.query.filter_by(is_active='Y').order_by(
        ERPSyncSchedule.hour, ERPSyncSchedule.minute
    ).all()

    # Active scheduled jobs for display
    active_jobs = {
        j.id: j.next_run_time
        for j in scheduler.get_jobs()
        if j.id.startswith('erp_sync_')
    }

    return render_template('admin/erp_sync.html',
                           sales_users=sales_users,
                           total_custs=total_custs,
                           erp_custs=erp_custs,
                           schedules=schedules,
                           active_jobs=active_jobs,
                           erp_configured=erp_service.is_configured())


# ── Manual sync ───────────────────────────────────────────────────────────────

def _run_sync_background(app, triggered_by_id, triggered_by_name):
    """Run the ERP sync in a background thread so the HTTP request returns immediately."""
    global _sync_status

    def _progress(log_type, msg):
        """Handle progress updates and log lines."""
        if log_type == 'progress':
            # msg is a dict — merge into progress counters
            _sync_status['progress'].update(msg)
            return
        # Otherwise append a timestamped log line
        entry = {
            'time': now_ist().strftime('%H:%M:%S'),
            'type': log_type,   # 'info' | 'success' | 'warn' | 'error'
            'msg':  msg,
        }
        logs = _sync_status.get('logs', [])
        if len(logs) < _MAX_LOGS:
            logs.append(entry)
        elif len(logs) == _MAX_LOGS:
            logs.append({'time': entry['time'], 'type': 'warn',
                         'msg': f'Log limit ({_MAX_LOGS}) reached — further entries suppressed.'})

    with app.app_context():
        try:
            result = erp_service.sync_from_erp(created_by=triggered_by_id,
                                               progress_cb=_progress)
            _sync_status['result'] = result
            _sync_status['error']  = None
            log_action('erp_sync', None, 'ERP_SYNC',
                       description=(
                           f"Manual ERP sync by {triggered_by_name}: "
                           f"{result['cust_created']} customers created, "
                           f"{result['cust_updated']} updated, "
                           f"{result['user_created']} salesreps created, "
                           f"{result['user_updated']} updated"
                       ),
                       new_values={k: v for k, v in result.items() if k != 'errors'})
        except Exception as e:
            _sync_status['error']  = str(e)
            _sync_status['result'] = None
            log_action('erp_sync', None, 'ERP_SYNC',
                       description=f"ERP sync failed: {e}")
        finally:
            _sync_status['running'] = False


@bp.route('/run', methods=['POST'])
@admin_required
def run_sync():
    global _sync_status
    if _sync_status['running']:
        flash('A sync is already in progress. Please wait.', 'warning')
        return redirect(url_for('erp_sync.index'))

    _sync_status = {
        'running': True, 'result': None, 'error': None,
        'started_at': now_ist(), 'logs': [],
        'progress': {'users_total': 0, 'users_done': 0,
                     'customers_total': 0, 'customers_done': 0},
    }

    t = threading.Thread(
        target=_run_sync_background,
        args=(current_app._get_current_object(),
              current_user.user_id, current_user.full_name),
        daemon=True,
    )
    t.start()
    flash('ERP sync started in the background. This page will update when it completes.', 'info')
    return redirect(url_for('erp_sync.sync_status'))


@bp.route('/status')
@admin_required
def sync_status():
    """Polling page — auto-refreshes every 5 s while sync is running."""
    return render_template('admin/erp_sync_status.html', sync=_sync_status)


# ── Schedule management ───────────────────────────────────────────────────────

@bp.route('/schedule/add', methods=['POST'])
@admin_required
def add_schedule():
    time_str = request.form.get('sync_time', '').strip()   # "HH:MM"
    label    = request.form.get('label', '').strip()

    if not time_str:
        flash('Please select a time.', 'danger')
        return redirect(url_for('erp_sync.index'))

    try:
        t = datetime.strptime(time_str, '%H:%M')
    except ValueError:
        flash('Invalid time format.', 'danger')
        return redirect(url_for('erp_sync.index'))

    # Prevent duplicate times
    existing = ERPSyncSchedule.query.filter_by(
        hour=t.hour, minute=t.minute, is_active='Y'
    ).first()
    if existing:
        flash(f'A sync at {time_str} IST already exists.', 'warning')
        return redirect(url_for('erp_sync.index'))

    s = ERPSyncSchedule(
        hour=t.hour, minute=t.minute,
        label=label or None,
        created_by=current_user.user_id,
        created_at=now_ist(),
    )
    db.session.add(s)
    db.session.commit()

    _reload_schedules()

    log_action('erp_sync', s.schedule_id, 'CREATE',
               description=f"ERP sync schedule added: {time_str} IST"
                           + (f" ({label})" if label else ''))
    flash(f'Sync scheduled at {time_str} IST.', 'success')
    return redirect(url_for('erp_sync.index'))


@bp.route('/schedule/<hashid:schedule_id>/delete', methods=['POST'])
@admin_required
def delete_schedule(schedule_id):
    s = ERPSyncSchedule.query.get_or_404(schedule_id)
    time_display = s.time_display
    s.is_active = 'N'
    db.session.commit()

    _reload_schedules()

    log_action('erp_sync', schedule_id, 'DELETE',
               description=f"ERP sync schedule removed: {time_display} IST")
    flash(f'Sync at {time_display} IST removed.', 'info')
    return redirect(url_for('erp_sync.index'))
