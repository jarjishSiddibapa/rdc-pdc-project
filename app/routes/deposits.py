"""
RDC PDC Manager — Deposit Routes
"""
from datetime import date, datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.cheque import Cheque
from app.models.deposit import ChequeDeposit
from app.models.bank import Bank
from app.services.cheque_service import transition_status
from app.services.audit_service import log_action
from app.decorators import role_required
from app.utils import now_ist, check_location_access

bp = Blueprint('deposits', __name__, url_prefix='/deposits')


@bp.route('/<hashid:cheque_id>/create', methods=['GET', 'POST'])
@role_required('Accounts', 'HO_Accounts')
def create(cheque_id):
    """Record a deposit for an accepted cheque."""
    cheque = Cheque.query.get_or_404(cheque_id)
    check_location_access(cheque)

    if cheque.status not in ('Accepted', 'Redeposited'):
        flash('Only accepted or redeposited cheques can be deposited.', 'warning')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    banks = Bank.query.filter_by(is_active='Y').order_by(Bank.bank_name).all()

    if request.method == 'POST':
        deposit_date = datetime.strptime(request.form.get('deposit_date'), '%Y-%m-%d').date()
        deposit_bank = request.form.get('deposit_bank', '').strip() or None

        deposit = ChequeDeposit(
            cheque_id=cheque.cheque_id,
            deposit_date=deposit_date,
            deposit_bank=deposit_bank,
            created_by=current_user.user_id,
            created_at=now_ist(),
        )
        db.session.add(deposit)
        db.session.commit()

        bank_note = f" — {deposit_bank}" if deposit_bank else ""
        success, error = transition_status(cheque, 'Deposited',
                                           f"Deposited on {deposit_date.strftime('%d %b %Y')}{bank_note}")

        log_action('cheque_deposits', deposit.deposit_id, 'CREATE',
                   description=f"Deposit created for cheque {cheque.uid}")

        if success:
            flash('Cheque deposited successfully!', 'success')
        else:
            flash(f'Deposit recorded but status change failed: {error}', 'warning')

        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    return render_template('deposits/form.html', cheque=cheque, banks=banks,
                           today=date.today().strftime('%Y-%m-%d'))
