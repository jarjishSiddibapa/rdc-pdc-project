"""
RDC PDC Manager — Admin Routes
User management, bank master, location master, email config, audit logs.
"""
import re as _re
import urllib.parse
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models.user import User
from app.models.bank import Bank
from app.models.location import Location
from app.models.audit import AuditLog
from app.models.settings import EmailConfig
from app.services.audit_service import log_action
from app.services.email_service import encrypt_password, decrypt_password, test_email_connection
from app.decorators import admin_required
from app.utils import now_ist

bp = Blueprint('admin', __name__, url_prefix='/admin')


# ─── PASSWORD STRENGTH ───────────────────────────────────────────

def _check_password_strength(password: str) -> tuple[bool, str]:
    """
    Returns (ok, error_message).
    A strong password must be ≥8 chars and contain at least one each of:
    uppercase, lowercase, digit, and special character.
    """
    if len(password) < 8:
        return False, 'Password must be at least 8 characters.'
    if not _re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter.'
    if not _re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter.'
    if not _re.search(r'\d', password):
        return False, 'Password must contain at least one number.'
    if not _re.search(r'[^A-Za-z0-9]', password):
        return False, 'Password must contain at least one special character (!@#$%^&* etc.).'
    return True, ''


# ─── USER MANAGEMENT ────────────────────────────────────────────

@bp.route('/users')
@admin_required
def users():
    """List all users, pre-split into three groups for the tab UI."""
    # Fetch every user — user counts are small, no pagination needed here
    all_users = (User.query
                 .options(joinedload(User.locations))
                 .order_by(User.full_name)
                 .all())

    active_users  = []
    pending_users = []   # ERP imported, awaiting activation
    inactive_users = []

    for u in all_users:
        if u._is_active == 'N' and u.salesrep_id:
            pending_users.append(u)
        elif u._is_active == 'Y':
            active_users.append(u)
        else:
            inactive_users.append(u)

    locations = Location.query.filter_by(is_active='Y').order_by(Location.location_name).all()
    all_sales_users = User.query.filter_by(role='Sales').order_by(User.full_name).all()

    return render_template('admin/users.html',
                           active_users=active_users,
                           pending_users=pending_users,
                           inactive_users=inactive_users,
                           roles=User.ROLE_CHOICES,
                           locations=locations,
                           all_sales_users=all_sales_users)


@bp.route('/users/create', methods=['GET', 'POST'])
@admin_required
def create_user():
    """Create a new user."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        role = request.form.get('role', '')
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        location_id = request.form.get('location_id', type=int)
        sales_person_id = request.form.get('sales_person_id', '').strip()

        locations = Location.query.filter_by(is_active='Y').order_by(Location.location_name).all()

        if not username or not full_name or not role or not password or not location_id:
            flash('Please fill in all required fields (location is mandatory).', 'danger')
            return render_template('admin/user_form.html', user=None, roles=User.ROLE_CHOICES, locations=locations)

        if User.query.filter_by(username=username).first():
            flash('Username already exists. Please choose a different username.', 'danger')
            return render_template('admin/user_form.html', user=None, roles=User.ROLE_CHOICES, locations=locations)

        if email and User.query.filter_by(email=email).first():
            flash('An account with this email address already exists.', 'danger')
            return render_template('admin/user_form.html', user=None, roles=User.ROLE_CHOICES, locations=locations)

        ok, pw_err = _check_password_strength(password)
        if not ok:
            flash(pw_err, 'danger')
            return render_template('admin/user_form.html', user=None, roles=User.ROLE_CHOICES, locations=locations)

        user = User(
            username=username,
            full_name=full_name,
            role=role,
            email=email,
            phone=phone,
            location_id=location_id or None,
            sales_person_id=sales_person_id or None,
            avatar_color=User.generate_avatar_color(),
            created_by=current_user.user_id,
            created_at=now_ist(),
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()   # get user_id before setting locations

        # Multi-location assignment
        loc_ids = request.form.getlist('location_ids', type=int)
        if not loc_ids and location_id:
            loc_ids = [location_id]
        user.locations = Location.query.filter(Location.location_id.in_(loc_ids)).all()

        db.session.commit()

        log_action('users', user.user_id, 'CREATE',
                   description=f"User '{username}' created with role '{role}'",
                   new_values={'username': username, 'role': role})

        flash(f'User "{full_name}" created successfully!', 'success')
        return redirect(url_for('admin.users'))

    locations = Location.query.filter_by(is_active='Y').order_by(Location.location_name).all()
    return render_template('admin/user_form.html', user=None, roles=User.ROLE_CHOICES, locations=locations)


@bp.route('/users/<hashid:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    """Edit an existing user."""
    user = User.query.get_or_404(user_id)
    locations = Location.query.filter_by(is_active='Y').order_by(Location.location_name).all()

    if request.method == 'POST':
        old_values = {'role': user.role, 'full_name': user.full_name, 'username': user.username}

        # Username — editable, must be unique
        new_username = request.form.get('username', '').strip().lower()
        if not new_username:
            flash('Username is required.', 'danger')
            return render_template('admin/user_form.html', user=user, roles=User.ROLE_CHOICES, locations=locations)
        if new_username != user.username:
            conflict = User.query.filter_by(username=new_username).first()
            if conflict and conflict.user_id != user.user_id:
                flash('Username already taken. Please choose a different one.', 'danger')
                return render_template('admin/user_form.html', user=user, roles=User.ROLE_CHOICES, locations=locations)
            user.username = new_username

        user.full_name       = request.form.get('full_name', '').strip()
        user.role            = request.form.get('role', '')
        new_email            = request.form.get('email', '').strip()
        user.phone           = request.form.get('phone', '').strip()

        if new_email and new_email != user.email:
            existing = User.query.filter_by(email=new_email).first()
            if existing and existing.user_id != user.user_id:
                flash('An account with this email address already exists.', 'danger')
                return render_template('admin/user_form.html', user=user, roles=User.ROLE_CHOICES, locations=locations)
        user.email = new_email
        user.location_id = request.form.get('location_id', type=int) or None

        # ERP-sourced fields are immutable once set by the ERP sync.
        # Only update them if this user was NOT imported from the ERP.
        if user.salesrep_id is None:
            user.sales_person_id = request.form.get('sales_person_id', '').strip() or None
            user.salesrep_id     = request.form.get('salesrep_id', type=int) or None

        user.updated_by      = current_user.user_id
        user.updated_at      = now_ist()

        # Multi-location: replace junction rows
        loc_ids = request.form.getlist('location_ids', type=int)
        if not loc_ids and user.location_id:
            loc_ids = [user.location_id]
        user.locations = Location.query.filter(Location.location_id.in_(loc_ids)).all() if loc_ids else []

        new_password = request.form.get('new_password', '').strip()
        if new_password:
            ok, pw_err = _check_password_strength(new_password)
            if not ok:
                flash(pw_err, 'danger')
                return render_template('admin/user_form.html', user=user, roles=User.ROLE_CHOICES, locations=locations)
            user.set_password(new_password)

        db.session.commit()

        log_action('users', user.user_id, 'UPDATE',
                   description=f"User '{user.username}' updated",
                   old_values=old_values,
                   new_values={'role': user.role, 'full_name': user.full_name})

        flash(f'User "{user.full_name}" updated successfully!', 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=user, roles=User.ROLE_CHOICES, locations=locations)


@bp.route('/users/<hashid:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_user(user_id):
    """Activate / Deactivate a user."""
    user = User.query.get_or_404(user_id)

    if user.user_id == current_user.user_id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin.users'))

    old_status = user._is_active
    user._is_active = 'N' if user._is_active == 'Y' else 'Y'
    user.updated_by = current_user.user_id
    user.updated_at = now_ist()
    db.session.commit()

    status = 'activated' if user._is_active == 'Y' else 'deactivated'
    log_action('users', user.user_id, 'UPDATE',
               description=f"User '{user.username}' {status}",
               old_values={'is_active': old_status},
               new_values={'is_active': user._is_active})

    flash(f'User "{user.full_name}" {status} successfully.', 'info')
    return redirect(url_for('admin.users'))


@bp.route('/users/<hashid:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_password(user_id):
    """Reset a user's password directly from the user list."""
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()

    if len(new_password) < 8:
        flash('Password must be at least 8 characters.', 'danger')
        return redirect(url_for('admin.users'))

    user.set_password(new_password)
    user.updated_by = current_user.user_id
    user.updated_at = now_ist()
    db.session.commit()

    log_action('users', user.user_id, 'UPDATE',
               description=f"Password reset for user '{user.username}' by admin")

    flash(f'Password for "{user.full_name}" has been reset.', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/users/<hashid:user_id>/activate', methods=['POST'])
@admin_required
def activate_user(user_id):
    """
    One-step activation for ERP-imported users:
    set location + password + activate in a single POST.
    """
    user = User.query.get_or_404(user_id)
    locations = Location.query.filter_by(is_active='Y').order_by(Location.location_name).all()

    location_id  = request.form.get('location_id', type=int)
    new_password = request.form.get('new_password', '').strip()

    if not location_id:
        flash('Please select a location to activate this user.', 'danger')
        return render_template('admin/user_form.html', user=user,
                               roles=User.ROLE_CHOICES, locations=locations)

    ok, pw_err = _check_password_strength(new_password)
    if not ok:
        flash(pw_err, 'danger')
        return render_template('admin/user_form.html', user=user,
                               roles=User.ROLE_CHOICES, locations=locations)

    user.location_id = location_id
    user.set_password(new_password)
    user._is_active  = 'Y'
    user.updated_by  = current_user.user_id
    user.updated_at  = now_ist()

    # Allow updating name / email / phone during activation.
    # ERP IDs (salesrep_id, sales_person_id) are set by the ERP sync and must not be overwritten.
    user.full_name = request.form.get('full_name', user.full_name).strip()
    user.email     = request.form.get('email', '').strip() or user.email
    user.phone     = request.form.get('phone', '').strip() or user.phone

    # Multi-location assignment
    loc_ids = request.form.getlist('location_ids', type=int)
    if not loc_ids and location_id:
        loc_ids = [location_id]
    if loc_ids:
        user.locations = Location.query.filter(Location.location_id.in_(loc_ids)).all()

    db.session.commit()

    log_action('users', user.user_id, 'UPDATE',
               description=f"ERP user '{user.username}' activated by {current_user.full_name}",
               new_values={'is_active': 'Y', 'location_id': location_id})

    flash(f'"{user.full_name}" has been activated and can now log in.', 'success')
    return redirect(url_for('admin.users', search=user.full_name))


@bp.route('/erp-users/purge', methods=['POST'])
@admin_required
def purge_erp_users():
    """
    Delete all inactive Sales users that were auto-created by ERP sync
    (those with salesrep_id set and _is_active = 'N').
    Allows a clean re-sync.
    """
    erp_users = User.query.filter(
        User.salesrep_id.isnot(None),
        User._is_active == 'N',
        User.role == 'Sales',
    ).all()

    count = len(erp_users)
    if not count:
        flash('No inactive ERP-synced users found.', 'info')
        return redirect(url_for('erp_sync.index'))

    user_ids = [u.user_id for u in erp_users]

    # Delete junction rows via the Table object (fully parameterized — no f-string SQL).
    # Bypasses the ORM identity map which gets stale when the ERP background thread
    # writes junction rows in a separate session (avoids StaleDataError).
    from app.models.associations import user_locations as _ul_table
    db.session.execute(
        _ul_table.delete().where(_ul_table.c.user_id.in_(user_ids))
    )
    db.session.flush()

    for u in erp_users:
        db.session.delete(u)
    db.session.commit()

    log_action('users', None, 'DELETE',
               description=f"Purged {count} inactive ERP-synced Sales user(s) by {current_user.full_name}")

    flash(f'{count} inactive ERP-synced user(s) removed. You can now re-run the ERP sync.',
          'success' if count else 'info')
    return redirect(url_for('erp_sync.index'))


@bp.route('/locations/purge-all', methods=['POST'])
@admin_required
def purge_all_locations():
    """
    Delete every row in the locations table.
    - Nulls users.location_id and cheques.location_id first (avoids FK errors).
    - user_locations / customer_locations junction rows cascade-delete automatically.
    Use before the first ERP location sync to wipe out old auto-created locations.
    """
    from app.models.cheque import Cheque
    from app.models.associations import user_locations as _ul, customer_locations as _cl

    # 1. Null the direct FKs on users + cheques
    User.query.filter(User.location_id.isnot(None)).update({'location_id': None},
                                                            synchronize_session=False)
    Cheque.query.filter(Cheque.location_id.isnot(None)).update({'location_id': None},
                                                                synchronize_session=False)
    db.session.flush()

    # 2. Clear junction tables (cascade would handle it, but be explicit)
    db.session.execute(_ul.delete())
    db.session.execute(_cl.delete())
    db.session.flush()

    # 3. Delete all locations
    count = Location.query.delete(synchronize_session=False)
    db.session.commit()

    log_action('locations', None, 'DELETE',
               description=f"Purged all {count} location(s) by {current_user.full_name} — ready for ERP location sync")

    flash(f'All {count} location(s) deleted. Run "Sync Locations" from ERP Sync to repopulate.', 'success')
    return redirect(url_for('erp_sync.index'))


@bp.route('/factory-reset', methods=['POST'])
@admin_required
def factory_reset():
    """
    Wipe ALL business data — keeps only the current admin user account.
    Tables cleared (in FK-safe order):
      cheque_resolution, cheque_deposits, cheque_status_history,
      reconciliation, cheques, customer_locations, customers,
      user_locations, locations, banks, notifications,
      audit_logs, erp_sync_schedules,
      users (all roles except Admin)
    """
    confirm = request.form.get('confirm_text', '').strip()
    if confirm != 'RESET':
        flash('Factory reset cancelled — confirmation text did not match.', 'danger')
        return redirect(url_for('erp_sync.index'))

    from sqlalchemy import text
    from app.models.associations import user_locations as _ul, customer_locations as _cl

    # ── 1. Child tables of cheques ────────────────────────────────────────────
    from app.models.resolution import ChequeResolution
    from app.models.deposit import ChequeDeposit
    from app.models.cheque import ChequeStatusHistory
    from app.models.reconciliation import Reconciliation

    ChequeResolution.query.delete(synchronize_session=False)
    ChequeDeposit.query.delete(synchronize_session=False)
    ChequeStatusHistory.query.delete(synchronize_session=False)
    Reconciliation.query.delete(synchronize_session=False)
    db.session.flush()

    # ── 2. Cheques ────────────────────────────────────────────────────────────
    from app.models.cheque import Cheque
    Cheque.query.delete(synchronize_session=False)
    db.session.flush()

    # ── 3. Customer junction + customers ─────────────────────────────────────
    db.session.execute(_cl.delete())
    from app.models.customer import Customer
    Customer.query.delete(synchronize_session=False)
    db.session.flush()

    # ── 4. User junction + locations + banks ─────────────────────────────────
    db.session.execute(_ul.delete())
    Location.query.delete(synchronize_session=False)
    Bank.query.delete(synchronize_session=False)
    db.session.flush()

    # ── 5. Notifications + audit logs + ERP schedules ────────────────────────
    from app.models.notification import Notification
    from app.models.erp_schedule import ERPSyncSchedule
    Notification.query.delete(synchronize_session=False)
    AuditLog.query.delete(synchronize_session=False)
    ERPSyncSchedule.query.delete(synchronize_session=False)
    db.session.flush()

    # ── 6. Non-admin users ───────────────────────────────────────────────────
    User.query.filter(User.role != 'Admin').delete(synchronize_session=False)
    db.session.flush()

    db.session.commit()

    # One fresh audit entry so the log isn't completely empty
    log_action('system', None, 'FACTORY_RESET',
               description=f"Factory reset performed by {current_user.full_name} — all business data wiped")

    flash('Factory reset complete. All business data has been wiped. Only the admin account remains.', 'success')
    return redirect(url_for('erp_sync.index'))


@bp.route('/users/merge', methods=['POST'])
@admin_required
def merge_users():
    """
    Merge two Sales person users.
    All cheques, customers, and location links from source move to target.
    Source user is then deactivated.
    """
    from app.models.cheque import Cheque
    from app.models.customer import Customer
    from app.models.associations import user_locations

    source_id = request.form.get('source_id', type=int)
    target_id = request.form.get('target_id', type=int)

    if not source_id or not target_id or source_id == target_id:
        flash('Please select two different users.', 'danger')
        return redirect(url_for('admin.users'))

    source = User.query.get_or_404(source_id)
    target = User.query.get_or_404(target_id)

    # Reassign cheques created by source → target
    cheque_count = Cheque.query.filter_by(created_by=source_id).update({'created_by': target_id})

    # Reassign cheques where salesperson is source → target
    sp_cheque_count = Cheque.query.filter_by(salesperson_id=source_id).update({'salesperson_id': target_id})

    # Reassign customers whose salesperson is source → target
    cust_count = Customer.query.filter_by(salesperson_id=source_id).update({'salesperson_id': target_id})

    # Merge location links: add source's locations to target (skip duplicates)
    target_loc_ids = {loc.location_id for loc in target.locations}
    for loc in source.locations:
        if loc.location_id not in target_loc_ids:
            target.locations.append(loc)

    # Stamp target with source's ERP IDs if target doesn't have them
    if not target.salesrep_id and source.salesrep_id:
        target.salesrep_id = source.salesrep_id
    if not target.sales_person_id and source.sales_person_id:
        target.sales_person_id = source.sales_person_id

    # Deactivate source
    source._is_active = 'N'
    source.updated_by = current_user.user_id
    source.updated_at = now_ist()

    db.session.commit()

    log_action('users', source_id, 'MERGE',
               description=(
                   f"User '{source.full_name}' merged into '{target.full_name}' "
                   f"by {current_user.full_name} — "
                   f"{cheque_count} cheques, {cust_count} customers reassigned"
               ))

    flash(
        f'"{source.full_name}" merged into "{target.full_name}". '
        f'{cheque_count} cheque(s) and {cust_count} customer(s) reassigned. '
        f'Source user deactivated.',
        'success'
    )
    return redirect(url_for('admin.users'))


# ─── BANK MANAGEMENT ────────────────────────────────────────────

@bp.route('/banks')
@admin_required
def banks():
    """List all banks with search and pagination."""

    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search   = request.args.get('search', '').strip()

    filter_qs = urllib.parse.urlencode(
        {k: v for k, v in request.args.items() if k not in ('page', 'per_page')}
    )

    query = Bank.query
    if search:
        query = query.filter(Bank.bank_name.ilike(f'%{search}%'))
    query = query.order_by(Bank.bank_name)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('admin/banks.html',
                           banks=pagination.items,
                           pagination=pagination,
                           per_page=per_page,
                           filter_qs=filter_qs,
                           search=search)


@bp.route('/banks/create', methods=['GET', 'POST'])
@admin_required
def create_bank():
    """Create a new bank."""
    if request.method == 'POST':
        bank = Bank(
            bank_name=request.form.get('bank_name', '').strip(),
        )
        db.session.add(bank)
        db.session.commit()

        log_action('banks', bank.bank_id, 'CREATE',
                   description=f"Bank '{bank.bank_name}' created")

        flash(f'Bank "{bank.bank_name}" created!', 'success')
        return redirect(url_for('admin.banks'))

    return render_template('admin/bank_form.html', bank=None)


@bp.route('/banks/<hashid:bank_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_bank(bank_id):
    """Edit a bank."""
    bank = Bank.query.get_or_404(bank_id)

    if request.method == 'POST':
        bank.bank_name = request.form.get('bank_name', '').strip()
        db.session.commit()

        log_action('banks', bank.bank_id, 'UPDATE',
                   description=f"Bank '{bank.bank_name}' updated")

        flash('Bank updated!', 'success')
        return redirect(url_for('admin.banks'))

    return render_template('admin/bank_form.html', bank=bank)


@bp.route('/banks/<hashid:bank_id>/toggle', methods=['POST'])
@admin_required
def toggle_bank(bank_id):
    """Activate / Deactivate a bank."""
    bank = Bank.query.get_or_404(bank_id)
    bank.is_active = 'N' if bank.is_active == 'Y' else 'Y'
    db.session.commit()
    flash(f'Bank "{bank.bank_name}" {"activated" if bank.is_active == "Y" else "deactivated"}.', 'info')
    return redirect(url_for('admin.banks'))


# ─── LOCATION MANAGEMENT ────────────────────────────────────────

@bp.route('/locations')
@admin_required
def locations():
    """List all locations with search and pagination."""

    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search   = request.args.get('search', '').strip()

    filter_qs = urllib.parse.urlencode(
        {k: v for k, v in request.args.items() if k not in ('page', 'per_page')}
    )

    query = Location.query
    if search:
        query = query.filter(Location.location_name.ilike(f'%{search}%'))
    query = query.order_by(Location.location_name)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('admin/locations.html',
                           locations=pagination.items,
                           pagination=pagination,
                           per_page=per_page,
                           filter_qs=filter_qs,
                           search=search)


@bp.route('/locations/create', methods=['GET', 'POST'])
@admin_required
def create_location():
    """Create a new location."""
    if request.method == 'POST':
        name = request.form.get('location_name', '').strip()

        if not name:
            flash('Location name is required.', 'danger')
            return render_template('admin/location_form.html', location=None)

        loc = Location(
            location_name=name,
            is_head_office='N',
        )
        db.session.add(loc)
        db.session.commit()

        log_action('locations', loc.location_id, 'CREATE',
                   description=f"Location '{name}' created")

        flash(f'Location "{name}" created!', 'success')
        return redirect(url_for('admin.locations'))

    return render_template('admin/location_form.html', location=None)


@bp.route('/locations/<hashid:location_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_location(location_id):
    """Edit a location."""
    loc = Location.query.get_or_404(location_id)

    if request.method == 'POST':
        loc.location_name = request.form.get('location_name', '').strip()

        db.session.commit()

        log_action('locations', loc.location_id, 'UPDATE',
                   description=f"Location '{loc.location_name}' updated")

        flash('Location updated!', 'success')
        return redirect(url_for('admin.locations'))

    return render_template('admin/location_form.html', location=loc)


@bp.route('/locations/<hashid:location_id>/toggle', methods=['POST'])
@admin_required
def toggle_location(location_id):
    """Activate / Deactivate a location."""
    loc = Location.query.get_or_404(location_id)
    loc.is_active = 'N' if loc.is_active == 'Y' else 'Y'
    db.session.commit()
    flash(f'Location "{loc.location_name}" {"activated" if loc.is_active == "Y" else "deactivated"}.', 'info')
    return redirect(url_for('admin.locations'))


@bp.route('/locations/merge', methods=['POST'])
@admin_required
def merge_locations():
    """
    Merge two locations — reassign all records from source to target,
    then deactivate the source location.
    """
    source_id = request.form.get('source_id', type=int)
    target_id = request.form.get('target_id', type=int)

    if not source_id or not target_id:
        flash('Please select both locations to merge.', 'danger')
        return redirect(url_for('admin.locations'))

    if source_id == target_id:
        flash('Source and target must be different locations.', 'danger')
        return redirect(url_for('admin.locations'))

    source = Location.query.get_or_404(source_id)
    target = Location.query.get_or_404(target_id)

    from app.models.cheque import Cheque
    from app.models.associations import user_locations, customer_locations

    # 1. Reassign cheques
    Cheque.query.filter_by(location_id=source_id).update({'location_id': target_id})

    # 2. Reassign primary location_id on users (legacy FK)
    from app.models.user import User as UserModel
    UserModel.query.filter_by(location_id=source_id).update({'location_id': target_id})

    # 3. Re-point user_locations junction rows to target (avoiding duplicates)
    #    First find users who already have target — skip them
    already_target = db.session.execute(
        user_locations.select().where(user_locations.c.location_id == target_id)
    ).fetchall()
    already_target_user_ids = {row.user_id for row in already_target}

    source_ul = db.session.execute(
        user_locations.select().where(user_locations.c.location_id == source_id)
    ).fetchall()
    for row in source_ul:
        if row.user_id not in already_target_user_ids:
            db.session.execute(
                user_locations.update()
                .where(user_locations.c.user_id == row.user_id)
                .where(user_locations.c.location_id == source_id)
                .values(location_id=target_id)
            )
        else:
            db.session.execute(
                user_locations.delete()
                .where(user_locations.c.user_id == row.user_id)
                .where(user_locations.c.location_id == source_id)
            )

    # 4. Re-point customer_locations junction rows to target (avoiding duplicates)
    already_target_c = db.session.execute(
        customer_locations.select().where(customer_locations.c.location_id == target_id)
    ).fetchall()
    already_target_cust_ids = {row.customer_id for row in already_target_c}

    source_cl = db.session.execute(
        customer_locations.select().where(customer_locations.c.location_id == source_id)
    ).fetchall()
    for row in source_cl:
        if row.customer_id not in already_target_cust_ids:
            db.session.execute(
                customer_locations.update()
                .where(customer_locations.c.customer_id == row.customer_id)
                .where(customer_locations.c.location_id == source_id)
                .values(location_id=target_id)
            )
        else:
            db.session.execute(
                customer_locations.delete()
                .where(customer_locations.c.customer_id == row.customer_id)
                .where(customer_locations.c.location_id == source_id)
            )

    # 5. Deactivate source
    source.is_active = 'N'
    db.session.commit()

    log_action('locations', source_id, 'DELETE',
               description=f"Location '{source.location_name}' merged into '{target.location_name}'")

    flash(f'"{source.location_name}" merged into "{target.location_name}" successfully.', 'success')
    return redirect(url_for('admin.locations'))


# ─── EMAIL SETTINGS ─────────────────────────────────────────────

# Gmail SMTP defaults — auto-applied, no need to ask users
GMAIL_SMTP_SERVER = 'smtp.gmail.com'
GMAIL_SMTP_PORT = 587

@bp.route('/email-settings', methods=['GET', 'POST'])
@admin_required
def email_settings():
    """Configure email (SMTP) settings — simplified for Gmail."""
    config = EmailConfig.query.first()

    if request.method == 'POST':
        gmail_address = request.form.get('gmail_address', '').strip()
        app_password = request.form.get('app_password', '').strip()
        sender_name = request.form.get('sender_name', '').strip() or 'RDC PDC Manager'

        if not gmail_address:
            flash('Gmail address is required.', 'danger')
            return render_template('admin/email_settings.html', config=config)

        # Encrypt password
        encrypted_pw = encrypt_password(app_password) if app_password else None

        if config:
            config.smtp_server = GMAIL_SMTP_SERVER
            config.smtp_port = GMAIL_SMTP_PORT
            config.smtp_username = gmail_address
            if encrypted_pw:
                config.smtp_password_encrypted = encrypted_pw
            config.sender_name = sender_name
            config.sender_email = gmail_address
            config.use_tls = 'Y'
            config.is_active = 'Y'
            config.updated_by = current_user.user_id
            config.updated_at = now_ist()
        else:
            if not app_password:
                flash('App Password is required for new configuration.', 'danger')
                return render_template('admin/email_settings.html', config=config)

            config = EmailConfig(
                smtp_server=GMAIL_SMTP_SERVER,
                smtp_port=GMAIL_SMTP_PORT,
                smtp_username=gmail_address,
                smtp_password_encrypted=encrypted_pw,
                sender_name=sender_name,
                sender_email=gmail_address,
                use_tls='Y',
                updated_by=current_user.user_id,
                updated_at=now_ist(),
            )
            db.session.add(config)

        db.session.commit()

        log_action('email_config', config.id, 'UPDATE',
                   description="Email settings updated")

        flash('Email settings saved successfully!', 'success')
        return redirect(url_for('admin.email_settings'))

    return render_template('admin/email_settings.html', config=config)


@bp.route('/email-settings/test', methods=['POST'])
@admin_required
def test_email():
    """Test Gmail SMTP connection."""
    gmail_address = request.form.get('gmail_address', '').strip()
    app_password = request.form.get('app_password', '').strip()

    # If no password provided, try to use existing saved config
    if not app_password:
        config = EmailConfig.query.first()
        if config:
            app_password = decrypt_password(config.smtp_password_encrypted)

    if not gmail_address or not app_password:
        return jsonify({'success': False, 'message': 'Gmail address and App Password are required'})

    success, error = test_email_connection(
        GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT,
        gmail_address, app_password, True
    )

    if success:
        return jsonify({'success': True, 'message': 'Connection successful!'})
    else:
        return jsonify({'success': False, 'message': f'Connection failed: {error}'})


# ─── AUDIT LOGS ──────────────────────────────────────────────────

@bp.route('/audit-logs')
@admin_required
def audit_logs():
    """View system audit logs."""

    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 30, type=int), 200)

    # Build query-string without page/per_page for use in pagination links
    filter_qs = urllib.parse.urlencode(
        {k: v for k, v in request.args.items() if k not in ('page', 'per_page')}
    )

    query = AuditLog.query

    action_filter = request.args.get('action', '')
    if action_filter:
        query = query.filter_by(action=action_filter)

    table_filter = request.args.get('table_name', '')
    if table_filter:
        query = query.filter_by(table_name=table_filter)

    user_filter = request.args.get('user_id', '', type=str)
    if user_filter:
        query = query.filter_by(user_id=int(user_filter))

    date_from = request.args.get('date_from', '')
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)

    date_to = request.args.get('date_to', '')
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to + ' 23:59:59')

    # Eager-load user relationship to avoid N+1 (one query per log row in template)
    query = (query
             .options(joinedload(AuditLog.user))
             .order_by(AuditLog.created_at.desc()))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    users = User.query.order_by(User.full_name).all()
    actions = ['CREATE', 'UPDATE', 'DELETE', 'STATUS_CHANGE', 'LOGIN', 'LOGOUT', 'ERP_SYNC']
    tables = ['users', 'cheques', 'customers', 'cheque_deposits', 'reconciliation',
              'cheque_resolution', 'email_config', 'banks', 'erp_sync']

    return render_template('admin/audit_logs.html',
                           logs=pagination.items,
                           pagination=pagination,
                           per_page=per_page,
                           filter_qs=filter_qs,
                           users=users,
                           actions=actions,
                           tables=tables,
                           filters=request.args)
