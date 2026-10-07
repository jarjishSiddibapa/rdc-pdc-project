"""
RDC PDC Manager — Cheque Routes
CRUD operations and workflow actions for cheques.
"""
import io
import os
from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, current_app, send_from_directory, send_file,
                   abort, jsonify)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload
import qrcode
from app.extensions import db
from app.models.cheque import Cheque, ChequeStatusHistory
from app.models.deposit import ChequeDeposit
from app.models.resolution import ChequeResolution
from app.models.customer import Customer
from app.models.bank import Bank
from app.models.location import Location
from app.models.user import User
from app.models.share_token import ChequeShareToken
from app.services.uid_generator import generate_uid
from app.services.cheque_service import (transition_status, get_available_transitions,
                                          VALID_TRANSITIONS, STATUS_ROLE_PERMISSIONS,
                                          LYING_WITH_MAP)
from app.services.audit_service import log_action
from app.services import notification_service
from app.decorators import role_required
from app.hashids_helper import hid_encode, hid_decode
from app.utils import now_ist, get_user_location_ids, check_location_access

bp = Blueprint('cheques', __name__, url_prefix='/cheques')


@bp.route('/uploads/<path:filename>')
@login_required
def serve_upload(filename):
    """
    Protected file-serving endpoint — requires an active session.
    Replaces direct /static/uploads/<file> access so cheque images,
    resolution documents and bank statements are never publicly accessible.
    Path-traversal is prevented by os.path.basename stripping any directory
    components; send_from_directory also enforces the root directory.
    """
    safe = os.path.basename(filename)
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    return send_from_directory(upload_dir, safe)


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']



@bp.route('/')
@login_required
def list_cheques():
    """List cheques — tabbed AJAX view (page shell only; data via /api/table)."""

    # Only dropdown data needed for the filter bar
    banks_list       = Bank.query.filter_by(is_active='Y').order_by(Bank.bank_name).all()
    locs_list        = []
    salespeople_list = []
    if current_user.role in ('Admin', 'HO_Accounts'):
        locs_list        = Location.query.filter_by(is_active='Y').order_by(Location.location_name).all()
        salespeople_list = User.query.filter_by(role='Sales', _is_active='Y').order_by(User.full_name).all()
    elif current_user.role == 'Accounts':
        salespeople_list = User.query.filter_by(role='Sales', _is_active='Y').order_by(User.full_name).all()

    lying_with_options = sorted(set(LYING_WITH_MAP.values()))

    return render_template('cheques/list.html',
                           statuses=Cheque.ALL_STATUSES,
                           banks_list=banks_list,
                           locs_list=locs_list,
                           salespeople_list=salespeople_list,
                           lying_with_options=lying_with_options)


@bp.route('/api/table')
@login_required
def api_table():
    """AJAX endpoint: paginated cheque data for the tabbed list view."""

    tab      = request.args.get('tab', 'action')
    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    sort_by  = request.args.get('sort_by', 'created_at')
    sort_dir = request.args.get('sort_dir', 'desc')
    search        = request.args.get('search', '').strip()
    status_f      = request.args.get('status', '')
    cheque_type_f = request.args.get('cheque_type', '')
    date_from     = request.args.get('date_from', '')
    date_to       = request.args.get('date_to', '')
    amount_from   = request.args.get('amount_from', '')
    amount_to     = request.args.get('amount_to', '')
    bank_id_f     = request.args.get('bank_id', '')
    loc_id_f      = request.args.get('location_id_filter', '')
    salesperson_f = request.args.get('salesperson_id', '')
    lying_with_f  = request.args.get('lying_with', '')
    customer_id_f = request.args.get('customer_id', '')

    # Role-scoped base query
    base_q = Cheque.query.filter_by(is_active='Y')
    if current_user.role == 'Sales':
        base_q = base_q.filter_by(created_by=current_user.user_id)
    elif current_user.role == 'Accounts' and not current_user.is_head_office_user:
        loc_ids = get_user_location_ids(current_user)
        if loc_ids:
            base_q = base_q.filter(Cheque.location_id.in_(loc_ids))

    # Build tab status sets
    ACTIVE_STATUSES   = set(VALID_TRANSITIONS.keys())
    TERMINAL_STATUSES = set(s for s in Cheque.ALL_STATUSES if s not in ACTIVE_STATUSES)
    actionable_statuses = set()
    for from_st, to_list in VALID_TRANSITIONS.items():
        for to_st in to_list:
            if current_user.role in STATUS_ROLE_PERMISSIONS.get(to_st, []):
                actionable_statuses.add(from_st)
                break
    inprogress_statuses = ACTIVE_STATUSES - actionable_statuses

    tab_status_map = {
        'action':   list(actionable_statuses) or ['__none__'],
        'progress': list(inprogress_statuses) or ['__none__'],
        'complete': list(TERMINAL_STATUSES)   or ['__none__'],
    }

    query = base_q.filter(Cheque.status.in_(tab_status_map.get(tab, tab_status_map['action'])))

    # Filters
    if status_f:
        query = query.filter_by(status=status_f)
    if cheque_type_f:
        query = query.filter_by(cheque_type=cheque_type_f)
    if lying_with_f:
        query = query.filter_by(lying_with=lying_with_f)
    if date_from:
        query = query.filter(Cheque.cheque_date >= date_from)
    if date_to:
        query = query.filter(Cheque.cheque_date <= date_to)
    if amount_from:
        try: query = query.filter(Cheque.amount >= float(amount_from))
        except ValueError: pass
    if amount_to:
        try: query = query.filter(Cheque.amount <= float(amount_to))
        except ValueError: pass
    if bank_id_f:
        try: query = query.filter_by(bank_id=int(bank_id_f))
        except ValueError: pass
    if loc_id_f and current_user.role in ('Admin', 'HO_Accounts'):
        try: query = query.filter_by(location_id=int(loc_id_f))
        except ValueError: pass
    if salesperson_f and current_user.role in ('Admin', 'HO_Accounts', 'Accounts'):
        try: query = query.filter_by(salesperson_id=int(salesperson_f))
        except ValueError: pass
    if customer_id_f:
        try: query = query.filter_by(customer_id=int(customer_id_f))
        except ValueError: pass
    if search:
        query = query.join(Customer, isouter=True).filter(
            or_(
                Cheque.uid.ilike(f'%{search}%'),
                Cheque.cheque_number.ilike(f'%{search}%'),
                Customer.customer_name.ilike(f'%{search}%'),
                Customer.customer_code.ilike(f'%{search}%'),
            )
        )

    # Sort
    _SORT = {
        'created_at':    Cheque.created_at,
        'cheque_date':   Cheque.cheque_date,
        'amount':        Cheque.amount,
        'cheque_number': Cheque.cheque_number,
        'status':        Cheque.status,
    }
    _scol  = _SORT.get(sort_by, Cheque.created_at)
    _order = _scol.desc() if sort_dir == 'desc' else _scol.asc()

    _eager = [
        joinedload(Cheque.customer), joinedload(Cheque.bank),
        joinedload(Cheque.location),
    ]
    pag = query.options(*_eager).order_by(_order).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Tab counts (applied against base query WITH current non-tab filters)
    def _count_tab(statuses):
        q = base_q.filter(Cheque.status.in_(statuses or ['__none__']))
        if search:
            q = q.join(Customer, isouter=True).filter(
                or_(
                    Cheque.uid.ilike(f'%{search}%'),
                    Cheque.cheque_number.ilike(f'%{search}%'),
                    Customer.customer_name.ilike(f'%{search}%'),
                    Customer.customer_code.ilike(f'%{search}%'),
                )
            )
        if cheque_type_f: q = q.filter_by(cheque_type=cheque_type_f)
        if date_from: q = q.filter(Cheque.cheque_date >= date_from)
        if date_to:   q = q.filter(Cheque.cheque_date <= date_to)
        return q.count()

    tab_counts = {
        'action':   _count_tab(list(actionable_statuses)),
        'progress': _count_tab(list(inprogress_statuses)),
        'complete': _count_tab(list(TERMINAL_STATUSES)),
    }

    cheque_list = []
    for c in pag.items:
        cheque_list.append({
            'uid':           c.uid,
            'url':           url_for('cheques.detail', cheque_id=c.cheque_id),
            'customer':      c.customer.customer_name if c.customer else '—',
            'customer_code': c.customer.customer_code if c.customer else '',
            'cheque_number': c.cheque_number or '—',
            'cheque_date':   c.cheque_date.strftime('%d %b %Y') if c.cheque_date else '—',
            'bank':          (c.bank.bank_name if c.bank else c.bank_name) or '—',
            'amount_display': c.amount_display,
            'amount':        float(c.amount or 0),
            'cheque_type':   c.cheque_type or '—',
            'status':        c.status,
            'status_color':  c.status_color,
            'location':      c.location.location_name if c.location else '—',
            'lying_with':    '' if c.status in TERMINAL_STATUSES else (c.lying_with or ''),
        })

    return jsonify({
        'cheques':    cheque_list,
        'page':       pag.page,
        'pages':      pag.pages,
        'total':      pag.total,
        'per_page':   per_page,
        'tab_counts': tab_counts,
    })


@bp.route('/create', methods=['GET', 'POST'])
@role_required('Sales')
def create():
    """Create a new cheque entry."""
    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        cheque_number = request.form.get('cheque_number', '').strip()
        cheque_date = request.form.get('cheque_date', '')
        amount = request.form.get('amount', type=float)
        cheque_type = request.form.get('cheque_type', 'PDC')
        remarks = request.form.get('remarks', '').strip()
        initial_status = request.form.get('initial_status', 'Collected by Sales Person')
        bank_id = request.form.get('bank_id', type=int) or None
        # Derive bank_name from the selected bank record so the text column is always populated
        bank_name = ''
        if bank_id:
            _bank = Bank.query.get(bank_id)
            if _bank:
                bank_name = _bank.bank_name

        # ── Server-side validation ────────────────────────────────────────────
        errors = []
        if not customer_id:           errors.append('Customer is required.')
        if not cheque_number:         errors.append('Cheque number is required.')
        if not cheque_date:           errors.append('Cheque date is required.')
        if not bank_id:               errors.append('Bank is required.')
        if not request.form.get('location_id', type=int):
                                      errors.append('Location is required.')
        if not amount or amount <= 0: errors.append('Amount must be greater than zero.')
        if cheque_date:
            try:
                datetime.strptime(cheque_date, '%Y-%m-%d')
            except ValueError:
                errors.append('Cheque date format is invalid.')
        # Cheque image — mandatory
        _img_file = request.files.get('cheque_image')
        if not _img_file or not _img_file.filename:
            errors.append('Cheque image is required.')
        elif not allowed_file(_img_file.filename):
            errors.append('Unsupported image format. Accepted: PNG, JPG, PDF.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('cheques.create'))

        # Handle file upload (already validated above)
        uploaded_file = None
        if _img_file and _img_file.filename and allowed_file(_img_file.filename):
            filename = secure_filename(f"{now_ist().strftime('%Y%m%d%H%M%S')}_{_img_file.filename}")
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_path, exist_ok=True)
            _img_file.save(os.path.join(upload_path, filename))
            uploaded_file = filename

        # Generate UID
        uid = generate_uid()

        # Determine lying_with based on initial status
        lying_with = LYING_WITH_MAP.get(initial_status, 'Customer')

        cheque = Cheque(
            uid=uid,
            customer_id=customer_id,
            cheque_number=cheque_number,
            cheque_date=datetime.strptime(cheque_date, '%Y-%m-%d').date(),
            bank_name=bank_name,
            bank_id=bank_id,
            amount=amount,
            cheque_type=cheque_type,
            status=initial_status,
            lying_with=lying_with,
            uploaded_file=uploaded_file,
            remarks=remarks,
            received_date=now_ist().date(),
            salesperson_id=current_user.user_id,
            location_id=request.form.get('location_id', type=int) or None,
            created_by=current_user.user_id,
            created_at=now_ist(),
        )
        db.session.add(cheque)
        db.session.flush()

        # Create initial status history
        history = ChequeStatusHistory(
            cheque_id=cheque.cheque_id,
            old_status=None,
            new_status=initial_status,
            old_lying_with=None,
            new_lying_with=lying_with,
            remarks=f"Cheque created — {remarks}" if remarks else "Cheque created",
            updated_by=current_user.user_id,
            updated_at=now_ist(),
        )
        db.session.add(history)
        db.session.commit()

        log_action('cheques', cheque.cheque_id, 'CREATE',
                   description=f"Cheque {uid} created for customer #{customer_id}",
                   new_values={'uid': uid, 'amount': str(amount), 'status': initial_status})

        # Notify Accounts
        try:
            notification_service.notify_cheque_created(cheque)
        except Exception:
            pass

        # ── If this cheque replaces an older one, close the old one now ─────────
        replaces_cheque_id = request.form.get('replaces_cheque_id', type=int)
        if replaces_cheque_id:
            old_cheque = Cheque.query.get(replaces_cheque_id)
            if old_cheque and old_cheque.status == 'Accepted':
                transition_status(
                    old_cheque, 'New Cheque Received',
                    f"Replaced by new cheque {uid}",
                )
                flash(f'Previous cheque {old_cheque.uid} has been closed as "New Cheque Received".', 'info')

        flash(f'Cheque {uid} created successfully!', 'success')
        return redirect(url_for('cheques.detail', cheque_id=cheque.cheque_id))

    # ── GET ──────────────────────────────────────────────────────────────────
    banks = Bank.query.filter_by(is_active='Y').order_by(Bank.bank_name).all()
    user_locations = sorted(current_user.locations, key=lambda l: l.location_name)

    # Replacement flow — pre-load old cheque so the form can pre-fill and show a banner
    replaces_cheque = None
    replaces_cheque_id_get = hid_decode(request.args.get('replaces', ''))
    if replaces_cheque_id_get:
        replaces_cheque = (
            Cheque.query
            .options(joinedload(Cheque.customer), joinedload(Cheque.bank), joinedload(Cheque.location))
            .filter_by(cheque_id=replaces_cheque_id_get, is_active='Y')
            .first()
        )

    return render_template('cheques/create.html',
                           banks=banks,
                           locations=user_locations,
                           replaces_cheque=replaces_cheque)


@bp.route('/<hashid:cheque_id>')
@login_required
def detail(cheque_id):
    """View cheque details."""
    cheque = (
        Cheque.query
        .options(
            joinedload(Cheque.customer),
            joinedload(Cheque.bank),
            joinedload(Cheque.location),
            joinedload(Cheque.salesperson),
            joinedload(Cheque.creator),
        )
        .filter_by(cheque_id=cheque_id)
        .first_or_404()
    )

    # Sales can only see their own
    if current_user.role == 'Sales' and cheque.created_by != current_user.user_id:
        abort(403)

    # Accounts can only see their location
    check_location_access(cheque)

    available_transitions = get_available_transitions(cheque)
    # Direct query so ascending order isn't overridden by the relationship's default desc()
    history = (ChequeStatusHistory.query
               .filter_by(cheque_id=cheque_id)
               .order_by(ChequeStatusHistory.updated_at.asc())
               .all())

    # Build next-step hints for the timeline
    _role_display = {
        'Sales': 'Sales', 'Accounts': 'Accounts',
        'HO_Accounts': 'HO Accounts',
    }
    next_steps = []
    for status in VALID_TRANSITIONS.get(cheque.status, []):
        # Skip Cleared/Bounced from the pending list when at Deposited —
        # the template shows the Cleared/Bounced action buttons directly
        if cheque.status == 'Deposited' and status in ('Cleared', 'Bounced'):
            continue
        roles = [_role_display.get(r, r) for r in STATUS_ROLE_PERMISSIONS.get(status, [])]
        next_steps.append({
            'status': status,
            'responsible': ' / '.join(roles) if roles else '—',
        })

    deposits = (ChequeDeposit.query
                .filter_by(cheque_id=cheque_id)
                .order_by(ChequeDeposit.created_at.asc())
                .all())
    resolutions = (ChequeResolution.query
                   .filter_by(cheque_id=cheque_id)
                   .order_by(ChequeResolution.created_at.asc())
                   .all())

    return render_template('cheques/detail.html',
                           cheque=cheque,
                           available_transitions=available_transitions,
                           history=history,
                           next_steps=next_steps,
                           deposits=deposits,
                           resolutions=resolutions)


@bp.route('/<hashid:cheque_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(cheque_id):
    """Edit cheque details (limited to certain roles/statuses)."""
    cheque = Cheque.query.get_or_404(cheque_id)

    # Only Admin or Creator (Sales) for non-finalized cheques
    if current_user.role == 'Sales' and cheque.created_by != current_user.user_id:
        abort(403)
    if current_user.role not in ('Admin', 'Sales', 'Accounts', 'HO_Accounts'):
        abort(403)

    # Accounts can only edit their location's cheques
    check_location_access(cheque)
    terminal = ('Cleared', 'Legal Notice Initiated', 'Cleared via NEFT',
                'New Cheque Received', 'Order Cancelled', 'Resolved')
    if cheque.status in terminal:
        flash('Cannot edit a finalized cheque.', 'warning')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    if request.method == 'POST':
        old_values = {
            'cheque_number': cheque.cheque_number,
            'amount': str(cheque.amount),
            'bank_name': cheque.bank_name,
            'remarks': cheque.remarks,
        }

        cheque.cheque_number = request.form.get('cheque_number', '').strip()
        cheque.cheque_date = datetime.strptime(request.form.get('cheque_date'), '%Y-%m-%d').date()
        cheque.bank_name = request.form.get('bank_name', '').strip()
        cheque.bank_id = request.form.get('bank_id', type=int) or None
        cheque.amount = request.form.get('amount', type=float)
        cheque.cheque_type = request.form.get('cheque_type', 'PDC')
        cheque.remarks = request.form.get('remarks', '').strip()
        # salesperson_id is immutable — set at creation, never changed
        cheque.location_id = request.form.get('location_id', type=int) or None
        cheque.updated_by = current_user.user_id
        cheque.updated_at = now_ist()

        # Handle file upload
        if 'cheque_image' in request.files:
            file = request.files['cheque_image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{now_ist().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                upload_path = os.path.join(current_app.root_path, 'static', 'uploads')
                os.makedirs(upload_path, exist_ok=True)
                file.save(os.path.join(upload_path, filename))
                cheque.uploaded_file = filename

        db.session.commit()

        new_values = {
            'cheque_number': cheque.cheque_number,
            'amount': str(cheque.amount),
            'bank_name': cheque.bank_name,
            'remarks': cheque.remarks,
        }
        log_action('cheques', cheque.cheque_id, 'UPDATE',
                   description=f"Cheque {cheque.uid} updated",
                   old_values=old_values, new_values=new_values)

        flash('Cheque updated successfully!', 'success')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    banks = Bank.query.filter_by(is_active='Y').order_by(Bank.bank_name).all()
    locations = Location.query.filter_by(is_active='Y').order_by(Location.location_name).all()
    return render_template('cheques/edit.html',
                           cheque=cheque, banks=banks, locations=locations)


@bp.route('/<hashid:cheque_id>/transition', methods=['POST'])
@login_required
def change_status(cheque_id):
    """Change cheque status (workflow transition)."""
    cheque = Cheque.query.get_or_404(cheque_id)

    # Location guard — Accounts can only act on their location
    check_location_access(cheque)

    new_status = request.form.get('new_status', '')
    remarks = request.form.get('remarks', '').strip()

    # ── Remarks mandatory for destructive / terminal transitions ─────────────
    REMARKS_REQUIRED = {
        'Rejected', 'Bounced', 'Order Cancelled',
        'Legal Notice Initiated', 'New Cheque Received',
    }
    if new_status in REMARKS_REQUIRED and not remarks:
        # Also accept new_cheque_number as the required text for "New Cheque Received"
        if new_status != 'New Cheque Received' or not request.form.get('new_cheque_number', '').strip():
            flash(f'Remarks are required when marking a cheque as "{new_status}".', 'danger')
            return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    # New Cheque Received — prepend the new cheque number to remarks
    new_cheque_number = request.form.get('new_cheque_number', '').strip()
    if new_status == 'New Cheque Received':
        if not new_cheque_number:
            flash('New cheque number is required when marking as "New Cheque Received".', 'danger')
            return redirect(url_for('cheques.detail', cheque_id=cheque_id))
        remarks = f"New Cheque #: {new_cheque_number}" + (f". {remarks}" if remarks else '')

    success, error = transition_status(cheque, new_status, remarks)

    if success:
        # Fire notifications that need context not available inside cheque_service
        try:
            if new_status == 'Cleared via NEFT':
                # remarks field doubles as NEFT reference for direct transitions
                notification_service.notify_cheque_neft(cheque, remarks)
        except Exception:
            pass
        flash(f'Status updated to "{new_status}".', 'success')
    else:
        flash(f'Status change failed: {error}', 'danger')

    return redirect(url_for('cheques.detail', cheque_id=cheque_id))


@bp.route('/<hashid:cheque_id>/delete', methods=['POST'])
@role_required('Admin')
def delete(cheque_id):
    """Soft delete a cheque."""
    cheque = Cheque.query.get_or_404(cheque_id)
    cheque.is_active = 'N'
    cheque.updated_by = current_user.user_id
    cheque.updated_at = now_ist()
    db.session.commit()

    log_action('cheques', cheque.cheque_id, 'DELETE',
               description=f"Cheque {cheque.uid} soft-deleted")

    flash(f'Cheque {cheque.uid} has been deactivated.', 'info')
    return redirect(url_for('cheques.list_cheques'))


@bp.route('/<hashid:cheque_id>/share', methods=['POST'])
@login_required
def generate_share_token(cheque_id):
    """Generate (or return existing) a public share token for the cheque image."""
    cheque = Cheque.query.get_or_404(cheque_id)
    if not cheque.uploaded_file:
        return jsonify({'error': 'No image has been uploaded for this cheque.'}), 400

    record = ChequeShareToken.get_or_create(cheque.cheque_id, current_user.user_id)
    share_url = url_for('public.view_cheque', token=record.token, _external=True)

    log_action('cheques', cheque.cheque_id, 'SHARE_LINK_GENERATED',
               description=f"Share link generated for cheque {cheque.uid} by '{current_user.username}'")

    return jsonify({'url': share_url, 'token': record.token})


@bp.route('/qr.png')
@login_required
def qr_png():
    """Return a QR code PNG for the given URL (server-side, same-origin)."""
    target_url = request.args.get('url', '')
    if not target_url:
        abort(400)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(target_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png',
                     max_age=3600, download_name='cheque-qr.png')


@bp.route('/api/customers/<hashid:customer_id>')
@login_required
def api_customer_info(customer_id):
    """API endpoint for customer auto-fill."""
    customer = Customer.query.get_or_404(customer_id)
    return jsonify({
        'customer_code': customer.customer_code,
        'customer_name': customer.customer_name,
        'contact_person': customer.contact_person,
        'contact_phone': customer.contact_phone,
    })


@bp.route('/api/customers/search')
@login_required
def api_customers_search():
    """
    AJAX endpoint for Tom Select remote customer search.
    Returns up to 50 matching customers as JSON.
    Used by the customer dropdown in cheque create/edit/list.
    """
    q = request.args.get('q', '').strip()
    results = []
    if q and len(q) >= 2:
        cust_q = Customer.query.filter(
            Customer.is_active == 'Y',
            or_(
                Customer.customer_name.ilike(f'%{q}%'),
                Customer.customer_code.ilike(f'%{q}%'),
            )
        )
        # Sales users only search within their own customers
        if current_user.role == 'Sales':
            cust_q = cust_q.filter(Customer.salesperson_id == current_user.user_id)
        customers = cust_q.order_by(Customer.customer_name).limit(50).all()
        results = [
            {
                'value': c.customer_id,
                'text': f'{c.customer_code} — {c.customer_name}',
                'customer_code': c.customer_code,
                'customer_name': c.customer_name,
            }
            for c in customers
        ]
    return jsonify(results)
