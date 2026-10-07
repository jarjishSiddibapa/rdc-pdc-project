"""
RDC PDC Manager — Reconciliation Routes

Accounts / HO_Accounts can mark a Deposited cheque as Cleared or Bounced directly
(no prerequisite bank-statement upload step).
"""
from datetime import datetime, date
from app.utils import now_ist
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models.cheque import Cheque
from app.models.reconciliation import Reconciliation
from app.services.cheque_service import transition_status
from app.services.audit_service import log_action
from app.decorators import role_required

bp = Blueprint('reconciliation', __name__, url_prefix='/reconciliation')


# ── Mark as Cleared ────────────────────────────────────────────────────────────

@bp.route('/<hashid:cheque_id>/clear', methods=['POST'])
@role_required('Accounts', 'HO_Accounts')
def mark_cleared(cheque_id):
    """Mark a deposited cheque as Cleared and record the ERP receipt number."""
    cheque = Cheque.query.get_or_404(cheque_id)

    if cheque.status != 'Deposited':
        flash('Only deposited cheques can be marked as Cleared.', 'warning')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    receipt_number = request.form.get('receipt_number', '').strip()
    cleared_date   = request.form.get('cleared_date', '').strip()
    remarks        = request.form.get('remarks', '').strip()

    if not receipt_number:
        flash('ERP receipt number is required to mark as Cleared.', 'danger')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    if not cleared_date:
        flash('Clearance date is required to mark as Cleared.', 'danger')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    # Create reconciliation record if it doesn't exist yet
    recon = cheque.reconciliation
    if not recon:
        recon = Reconciliation(
            cheque_id   = cheque.cheque_id,
            uploaded_by = current_user.user_id,
            uploaded_at = now_ist(),
        )
        db.session.add(recon)
        db.session.flush()

    recon.is_cleared    = 'Y'
    recon.receipt_number = receipt_number
    recon.cleared_date  = (datetime.strptime(cleared_date, '%Y-%m-%d').date()
                           if cleared_date else date.today())
    db.session.commit()

    success, error = transition_status(cheque, 'Cleared', remarks or f'Receipt: {receipt_number}')

    log_action('reconciliation', recon.recon_id, 'CLEARED',
               description=f"Cheque {cheque.uid} marked Cleared; receipt {receipt_number}")

    if success:
        flash('Cheque marked as Cleared!', 'success')
    else:
        flash(f'Receipt saved but status change failed: {error}', 'warning')

    return redirect(url_for('cheques.detail', cheque_id=cheque_id))


# ── Mark as Bounced ────────────────────────────────────────────────────────────

@bp.route('/<hashid:cheque_id>/bounce', methods=['POST'])
@role_required('Accounts', 'HO_Accounts')
def mark_bounced(cheque_id):
    """Mark a deposited cheque as Bounced."""
    cheque = Cheque.query.get_or_404(cheque_id)

    if cheque.status != 'Deposited':
        flash('Only deposited cheques can be marked as Bounced.', 'warning')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    remarks = request.form.get('remarks', '').strip()

    if not remarks:
        flash('Remarks are required when marking a cheque as Bounced.', 'danger')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    # Create reconciliation record if it doesn't exist yet
    recon = cheque.reconciliation
    if not recon:
        recon = Reconciliation(
            cheque_id   = cheque.cheque_id,
            uploaded_by = current_user.user_id,
            uploaded_at = now_ist(),
        )
        db.session.add(recon)
        db.session.flush()

    recon.is_cleared = 'N'
    db.session.commit()

    success, error = transition_status(cheque, 'Bounced', remarks or 'Cheque bounced.')

    log_action('reconciliation', recon.recon_id, 'BOUNCED',
               description=f"Cheque {cheque.uid} marked Bounced")

    if success:
        flash('Cheque marked as Bounced.', 'warning')
    else:
        flash(f'Status change failed: {error}', 'warning')

    return redirect(url_for('cheques.detail', cheque_id=cheque_id))
