"""
RDC PDC Manager — Dashboard Routes
Role-based dashboards with location-wise filtering.
"""
from datetime import date
from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models.cheque import Cheque
from app.models.customer import Customer
from app.models.location import Location
from app.models.user import User

bp = Blueprint('dashboard', __name__)


def _get_location_filter():
    """
    Returns the location_id to filter by.

    - Admin / HO_Accounts:
        Default = all locations (loc_id = None).
        Optional override via ?location_id= query param.
    - Accounts:
        Locked to their assigned location (current_user.location_id).
        If no location_id is set, shows all (edge case — shouldn't happen).
    - Sales:
        Scope applied via created_by filter elsewhere; returns None here.
    """
    if current_user.role in ('Admin', 'HO_Accounts'):
        return request.args.get('location_id', type=int)  # None = all locations
    return current_user.location_id  # Accounts locked to their location


def _get_base_stats(location_id=None):
    """
    Common statistics, optionally scoped to a location.
    Uses a single GROUP BY query instead of one query per status.
    """
    loc_filter = [Cheque.is_active == 'Y']
    if location_id:
        loc_filter.append(Cheque.location_id == location_id)

    # ── Single aggregation query: count + sum grouped by status ──────────────
    rows = db.session.query(
        Cheque.status,
        func.count(Cheque.cheque_id).label('cnt'),
        func.coalesce(func.sum(Cheque.amount), 0).label('amt'),
    ).filter(*loc_filter).group_by(Cheque.status).all()

    agg = {r.status: {'count': r.cnt, 'amount': float(r.amt)} for r in rows}

    # Ensure every known status has an entry (zero if no data)
    stats_by_status = {
        s: agg.get(s, {'count': 0, 'amount': 0.0})
        for s in Cheque.ALL_STATUSES
    }

    total_cheques = sum(v['count'] for v in stats_by_status.values())
    total_amount  = sum(v['amount'] for v in stats_by_status.values())

    first_of_month = date.today().replace(day=1)
    month_filter = loc_filter + [Cheque.created_at >= first_of_month]
    try:
        month_row = db.session.query(
            func.count(Cheque.cheque_id).label('cnt'),
            func.coalesce(func.sum(Cheque.amount), 0).label('amt'),
        ).filter(*month_filter).one()
        this_month_count  = month_row.cnt or 0
        this_month_amount = float(month_row.amt or 0)
    except Exception:
        this_month_count  = 0
        this_month_amount = 0.0

    # Eager-load relationships so dashboard table has no N+1
    recent_cheques = (
        Cheque.query
        .filter(*loc_filter)
        .options(
            joinedload(Cheque.customer),
            joinedload(Cheque.bank),
            joinedload(Cheque.location),
            joinedload(Cheque.salesperson),
        )
        .order_by(Cheque.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        'total_cheques':     total_cheques,
        'total_amount':      total_amount,
        'stats_by_status':   stats_by_status,
        'this_month_count':  this_month_count,
        'this_month_amount': this_month_amount,
        'recent_cheques':    recent_cheques,
        'status_colors':     Cheque.STATUS_COLORS,
    }


def _location_context():
    """
    Returns locations list, selected_location_id, and clear_url for the
    location filter dropdown shown to Admin / HO_Accounts.
    Accounts and Sales get an empty dict (no dropdown).
    """
    _clear_url_map = {
        'Admin':       'dashboard.admin_dashboard',
        'HO_Accounts': 'dashboard.ho_accounts_dashboard',
    }
    if current_user.role not in _clear_url_map:
        return {}
    locations = Location.query.filter_by(is_active='Y').order_by(Location.location_name).all()
    selected  = request.args.get('location_id', type=int)
    return {
        'locations':            locations,
        'selected_location_id': selected,
        'location_filter_clear_url': url_for(_clear_url_map[current_user.role]),
    }


@bp.route('/')
@bp.route('/dashboard')
@login_required
def index():
    role_map = {
        'Admin':       'dashboard.admin_dashboard',
        'Sales':       'dashboard.sales_dashboard',
        'Accounts':    'dashboard.accounts_dashboard',
        'HO_Accounts': 'dashboard.ho_accounts_dashboard',
    }
    return redirect(url_for(role_map.get(current_user.role, 'dashboard.sales_dashboard')))


@bp.route('/dashboard/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'Admin':
        return redirect(url_for('dashboard.index'))

    loc_id = _get_location_filter()
    stats = _get_base_stats(loc_id)
    stats['total_customers'] = Customer.query.filter_by(is_active='Y').count()
    stats['total_users'] = User.query.filter_by(_is_active='Y').count()
    stats.update(_location_context())
    return render_template('dashboard/admin.html', **stats)


@bp.route('/dashboard/sales')
@login_required
def sales_dashboard():
    if current_user.role not in ('Sales', 'Admin'):
        return redirect(url_for('dashboard.index'))

    loc_id = _get_location_filter()
    stats = _get_base_stats(loc_id)

    if current_user.role == 'Sales':
        # Single GROUP BY to get all per-status counts in one round-trip
        my_filters = [Cheque.created_by == current_user.user_id, Cheque.is_active == 'Y']
        if loc_id:
            my_filters.append(Cheque.location_id == loc_id)
        my_rows = (db.session.query(Cheque.status, func.count(Cheque.cheque_id).label('cnt'))
                   .filter(*my_filters).group_by(Cheque.status).all())
        my_by_status = {r.status: r.cnt for r in my_rows}
        stats['my_cheques_count'] = sum(my_by_status.values())
        stats['my_pending']   = my_by_status.get('Pending with Customer', 0)
        stats['my_collected'] = my_by_status.get('Collected by Sales Person', 0)
        stats['my_rejected']  = my_by_status.get('Rejected', 0)
        stats['recent_cheques'] = (Cheque.query
            .filter(*my_filters)
            .options(joinedload(Cheque.customer), joinedload(Cheque.bank),
                     joinedload(Cheque.location))
            .order_by(Cheque.created_at.desc()).limit(10).all())

    stats.update(_location_context())
    loc_name = current_user.user_location.location_name if current_user.user_location else None
    stats['location_name'] = loc_name
    return render_template('dashboard/sales.html', **stats)


@bp.route('/dashboard/accounts')
@login_required
def accounts_dashboard():
    if current_user.role not in ('Accounts', 'Admin'):
        return redirect(url_for('dashboard.index'))

    loc_id = _get_location_filter()
    stats = _get_base_stats(loc_id)

    base_q = Cheque.query.filter_by(is_active='Y')
    if loc_id:
        base_q = base_q.filter_by(location_id=loc_id)

    stats['pending_approval'] = base_q.filter_by(status='Collected by Sales Person').count()
    stats['pending_deposit'] = base_q.filter_by(status='Accepted').count()
    stats['amount_pending_deposit'] = float(db.session.query(
        func.coalesce(func.sum(Cheque.amount), 0)
    ).filter(
        Cheque.is_active == 'Y', Cheque.status == 'Accepted',
        *([Cheque.location_id == loc_id] if loc_id else [])
    ).scalar())

    stats.update(_location_context())
    loc_name = current_user.user_location.location_name if current_user.user_location else None
    stats['location_name'] = loc_name
    return render_template('dashboard/accounts.html', **stats)


@bp.route('/dashboard/credit-control')
@login_required
def credit_control_dashboard():
    if current_user.role not in ('HO_Accounts', 'Admin', 'Credit_Control'):
        return redirect(url_for('dashboard.ho_accounts_dashboard'))

    loc_id = _get_location_filter()
    stats = _get_base_stats(loc_id)

    base_q = Cheque.query.filter_by(is_active='Y')
    if loc_id:
        base_q = base_q.filter_by(location_id=loc_id)

    stats['bounced_cheques'] = base_q.filter_by(status='Bounced').count()
    stats['bounced_amount'] = float(db.session.query(
        func.coalesce(func.sum(Cheque.amount), 0)
    ).filter(
        Cheque.is_active == 'Y', Cheque.status == 'Bounced',
        *([Cheque.location_id == loc_id] if loc_id else [])
    ).scalar())
    stats['legal_cheques']    = base_q.filter_by(status='Legal Notice Initiated').count()
    stats['neft_cleared']     = base_q.filter_by(status='Cleared via NEFT').count()
    stats['neft_requested']   = base_q.filter_by(status='NEFT Received').count()
    stats['recent_bounced']   = base_q.filter_by(status='Bounced').order_by(
        Cheque.updated_at.desc()).limit(10).all()

    stats.update(_location_context())
    loc_name = current_user.user_location.location_name if current_user.user_location else None
    stats['location_name'] = loc_name
    return render_template('dashboard/credit_control.html', **stats)


@bp.route('/dashboard/ho-accounts')
@login_required
def ho_accounts_dashboard():
    if current_user.role not in ('HO_Accounts', 'Admin'):
        return redirect(url_for('dashboard.index'))

    loc_id = _get_location_filter()
    stats = _get_base_stats(loc_id)

    base_q = Cheque.query.filter_by(is_active='Y')
    if loc_id:
        base_q = base_q.filter_by(location_id=loc_id)

    stats['deposited_cheques'] = base_q.filter_by(status='Deposited').count()
    stats['deposited_amount'] = float(db.session.query(
        func.coalesce(func.sum(Cheque.amount), 0)
    ).filter(
        Cheque.is_active == 'Y', Cheque.status == 'Deposited',
        *([Cheque.location_id == loc_id] if loc_id else [])
    ).scalar())
    stats['cleared_this_month'] = base_q.filter(
        Cheque.status == 'Cleared',
        Cheque.updated_at >= date.today().replace(day=1)
    ).count()

    stats.update(_location_context())
    loc_name = current_user.user_location.location_name if current_user.user_location else None
    stats['location_name'] = loc_name
    return render_template('dashboard/ho_accounts.html', **stats)
