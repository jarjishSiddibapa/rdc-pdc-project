"""
RDC PDC Manager — Customer Routes
"""
import urllib.parse
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models.customer import Customer
from app.models.location import Location
from app.models.associations import customer_locations
from app.models.user import User
from app.services.audit_service import log_action
from app.decorators import role_required
from app.utils import now_ist

bp = Blueprint('customers', __name__, url_prefix='/customers')


@bp.route('/')
@login_required
def list_customers():
    """List all customers with search and pagination."""
    page              = request.args.get('page', 1, type=int)
    per_page          = min(request.args.get('per_page', current_app.config.get('ITEMS_PER_PAGE', 20), type=int), 100)
    search            = request.args.get('search', '').strip()
    salesperson_filter = request.args.get('salesperson_id', '', type=str)
    sort_by           = request.args.get('sort_by', 'customer_name')
    sort_dir          = request.args.get('sort_dir', 'asc')
    # Query string without sort/page/per_page — used by sort headers & pagination macro
    filter_qs = urllib.parse.urlencode(
        {k: v for k, v in request.args.items() if k not in ('sort_by', 'sort_dir', 'page', 'per_page')}
    )

    query = Customer.query

    show_inactive = request.args.get('show_inactive', '') == 'on'
    if not show_inactive:
        query = query.filter_by(is_active='Y')

    if search:
        query = query.filter(
            db.or_(
                Customer.customer_name.ilike(f'%{search}%'),
                Customer.customer_code.ilike(f'%{search}%'),
                Customer.city.ilike(f'%{search}%'),
                Customer.contact_person.ilike(f'%{search}%'),
            )
        )

    salespeople = User.query.filter_by(role='Sales', _is_active='Y').order_by(User.full_name).all()

    # Sales users can only see their own customers
    if current_user.role == 'Sales':
        query = query.filter(Customer.salesperson_id == current_user.user_id)
    elif salesperson_filter:
        query = query.filter(Customer.salesperson_id == int(salesperson_filter))

    # Sorting
    _SORT_COLS = {
        'customer_name': Customer.customer_name,
        'customer_code': Customer.customer_code,
        'city':          Customer.city,
        'created_at':    Customer.created_at,
    }
    _col = _SORT_COLS.get(sort_by, Customer.customer_name)
    query = query.order_by(_col.asc() if sort_dir == 'asc' else _col.desc())

    # Eagerly load salesperson so the template doesn't issue N+1 queries
    query = query.options(joinedload(Customer.salesperson))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)


    # If filtered to a specific salesperson, pass their name for the heading
    active_salesperson = None
    if salesperson_filter:
        active_salesperson = User.query.get(int(salesperson_filter))

    return render_template('customers/list.html',
                           customers=pagination.items,
                           pagination=pagination,
                           per_page=per_page,
                           salespeople=salespeople,
                           active_salesperson=active_salesperson,
                           filters=request.args,
                           sort_by=sort_by,
                           sort_dir=sort_dir,
                           filter_qs=filter_qs)


@bp.route('/create', methods=['GET', 'POST'])
@role_required('Admin', 'Sales', 'Accounts', 'HO_Accounts')
def create():
    """Create a new customer."""
    if request.method == 'POST':
        code = request.form.get('customer_code', '').strip().upper()
        name = request.form.get('customer_name', '').strip()

        if not code or not name:
            flash('Customer code and name are required.', 'danger')
            return render_template('customers/form.html', customer=None)

        if Customer.query.filter_by(customer_code=code).first():
            flash('Customer code already exists.', 'danger')
            return render_template('customers/form.html', customer=None)

        customer = Customer(
            customer_code=code,
            customer_name=name,
            contact_person=request.form.get('contact_person', '').strip(),
            contact_phone=request.form.get('contact_phone', '').strip(),
            contact_email=request.form.get('contact_email', '').strip(),
            address=request.form.get('address', '').strip(),
            city=request.form.get('city', '').strip(),
            gst_number=request.form.get('gst_number', '').strip().upper(),
            created_by=current_user.user_id,
            created_at=now_ist(),
        )
        db.session.add(customer)
        db.session.commit()

        log_action('customers', customer.customer_id, 'CREATE',
                   description=f"Customer '{name}' ({code}) created",
                   new_values={'code': code, 'name': name})

        flash(f'Customer "{name}" created successfully!', 'success')
        return redirect(url_for('customers.list_customers'))

    return render_template('customers/form.html', customer=None)


@bp.route('/<hashid:customer_id>/edit', methods=['GET', 'POST'])
@role_required('Admin', 'Sales', 'Accounts', 'HO_Accounts')
def edit(customer_id):
    """Edit an existing customer."""
    customer = Customer.query.get_or_404(customer_id)

    if request.method == 'POST':
        old_values = {'name': customer.customer_name, 'city': customer.city}

        customer.customer_name = request.form.get('customer_name', '').strip()
        customer.contact_person = request.form.get('contact_person', '').strip()
        customer.contact_phone = request.form.get('contact_phone', '').strip()
        customer.contact_email = request.form.get('contact_email', '').strip()
        customer.address = request.form.get('address', '').strip()
        customer.city = request.form.get('city', '').strip()
        customer.gst_number = request.form.get('gst_number', '').strip().upper()
        customer.updated_at = now_ist()

        db.session.commit()

        log_action('customers', customer.customer_id, 'UPDATE',
                   description=f"Customer '{customer.customer_name}' updated",
                   old_values=old_values,
                   new_values={'name': customer.customer_name, 'city': customer.city})

        flash(f'Customer updated successfully!', 'success')
        return redirect(url_for('customers.list_customers'))

    return render_template('customers/form.html', customer=customer)


@bp.route('/<hashid:customer_id>/toggle', methods=['POST'])
@role_required('Admin')
def toggle(customer_id):
    """Activate / Deactivate a customer."""
    customer = Customer.query.get_or_404(customer_id)
    customer.is_active = 'N' if customer.is_active == 'Y' else 'Y'
    customer.updated_at = now_ist()
    db.session.commit()

    status = 'activated' if customer.is_active == 'Y' else 'deactivated'
    log_action('customers', customer.customer_id, 'UPDATE',
               description=f"Customer '{customer.customer_name}' {status}")

    flash(f'Customer {status} successfully.', 'info')
    return redirect(url_for('customers.list_customers'))
