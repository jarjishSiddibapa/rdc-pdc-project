"""
RDC PDC Manager — Cheque Workflow Service
Enforces status transitions and lying_with rules.
"""
import logging
from datetime import datetime
from app.utils import now_ist
from flask_login import current_user
from app.extensions import db
from app.models.cheque import Cheque, ChequeStatusHistory
from app.services.audit_service import log_action

log = logging.getLogger(__name__)
from app.services import notification_service


# Valid status transitions: current_status -> [allowed_next_statuses]
VALID_TRANSITIONS = {
    'Pending with Customer':    ['Collected by Sales Person'],
    'Collected by Sales Person': ['Accepted', 'Rejected'],
    'Rejected':                 ['Collected by Sales Person'],
    # Accepted has two actor groups:
    #   Accounts/CC → Deposited or Rejected
    #   Sales       → New Cheque Received / NEFT Received / Order Cancelled
    'Accepted': ['Deposited', 'Rejected', 'New Cheque Received', 'NEFT Received', 'Order Cancelled'],
    'Deposited': ['Cleared', 'Bounced'],
    'Bounced':    ['Legal Notice Initiated', 'Cleared via NEFT', 'Redeposited'],
    'Redeposited': ['Deposited', 'Rejected'],
    # NEFT Received → CC confirms and marks Cleared via NEFT
    'NEFT Received': ['Cleared via NEFT'],
}

# Who holds the cheque at each status
LYING_WITH_MAP = {
    'Pending with Customer':    'Customer',
    'Collected by Sales Person': 'Sales',
    'Accepted':                 'Accounts',
    'Rejected':                 'Sales',
    'Deposited':                'Bank',
    'Cleared':                  'HO Accounts',
    'Bounced':                  'Credit Control',
    'Redeposited':              'Accounts',
    'Legal Notice Initiated':   'Credit Control',
    'Cleared via NEFT':         'HO Accounts',
    'New Cheque Received':      'Sales',
    'NEFT Received':            'Credit Control',
    'Order Cancelled':          'Sales',
    'Resolved':                 'Credit Control',  # legacy
}

# Which roles can transition to which statuses
# Admin is intentionally excluded — Admin is view-only on cheque workflow
STATUS_ROLE_PERMISSIONS = {
    'Collected by Sales Person': ['Sales'],
    'Accepted':                 ['Accounts', 'HO_Accounts'],
    'Rejected':                 ['Accounts', 'HO_Accounts'],
    'Deposited':                ['Accounts', 'HO_Accounts'],
    'Cleared':                  ['Accounts', 'HO_Accounts'],
    'Bounced':                  ['Accounts', 'HO_Accounts'],
    'Redeposited':              ['Accounts', 'HO_Accounts'],
    'Legal Notice Initiated':   ['Accounts', 'HO_Accounts'],
    'Cleared via NEFT':         ['Accounts', 'HO_Accounts'],
    'New Cheque Received':      ['Sales'],
    'NEFT Received':            ['Sales'],
    'Order Cancelled':          ['Sales'],
    'Resolved':                 ['Accounts', 'HO_Accounts'],  # legacy
}

# Notification handlers for each new status
NOTIFICATION_MAP = {
    'Collected by Sales Person': notification_service.notify_cheque_collected,
    'Accepted':               notification_service.notify_cheque_accepted,
    'Rejected':               None,   # handled below — always fires with reason
    'Deposited':              notification_service.notify_cheque_deposited,
    'Cleared':                notification_service.notify_cheque_cleared,
    'Bounced':                notification_service.notify_cheque_bounced,
    'Legal Notice Initiated': notification_service.notify_cheque_legal,
    'Cleared via NEFT':       None,   # fired explicitly from resolution.py or change_status (with NEFT ref)
    'New Cheque Received':    notification_service.notify_cheque_new_cheque_received,
    'NEFT Received':          notification_service.notify_cheque_neft_received,
    'Order Cancelled':        None,
    'Redeposited':            None,   # notification fired separately in resolution.py
    'Resolved':               None,   # legacy
}


def can_transition(cheque, new_status, user_role=None):
    """
    Check if a cheque can transition to the given status.

    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    if user_role is None:
        user_role = current_user.role

    allowed_statuses = VALID_TRANSITIONS.get(cheque.status, [])
    if new_status not in allowed_statuses:
        return False, f"Cannot transition from '{cheque.status}' to '{new_status}'"

    allowed_roles = STATUS_ROLE_PERMISSIONS.get(new_status, [])
    if user_role not in allowed_roles:
        return False, f"Your role ({user_role}) is not authorized for this action"

    return True, None


def transition_status(cheque, new_status, remarks=None, user=None):
    """
    Transition a cheque to a new status.

    Args:
        cheque: Cheque model instance
        new_status: Target status string
        remarks: Optional remarks
        user: User performing the action (defaults to current_user)

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    if user is None:
        user = current_user

    # Validate transition
    allowed, error = can_transition(cheque, new_status, user.role)
    if not allowed:
        return False, error

    old_status = cheque.status
    old_lying = cheque.lying_with

    # Create status history record
    history = ChequeStatusHistory(
        cheque_id=cheque.cheque_id,
        old_status=old_status,
        new_status=new_status,
        old_lying_with=old_lying,
        new_lying_with=LYING_WITH_MAP.get(new_status, old_lying),
        remarks=remarks,
        updated_by=user.user_id,
        updated_at=now_ist(),
    )
    db.session.add(history)

    # Update cheque
    cheque.status = new_status
    cheque.lying_with = LYING_WITH_MAP.get(new_status, old_lying)
    cheque.updated_by = user.user_id
    cheque.updated_at = now_ist()

    db.session.commit()

    # Audit log
    log_action(
        'cheques', cheque.cheque_id, 'STATUS_CHANGE',
        description=f"Status changed from '{old_status}' to '{new_status}'",
        old_values={'status': old_status, 'lying_with': old_lying},
        new_values={'status': new_status, 'lying_with': cheque.lying_with},
    )

    # Send notifications
    try:
        handler = NOTIFICATION_MAP.get(new_status)
        if new_status == 'Rejected':
            notification_service.notify_cheque_rejected(cheque, remarks or '')
        elif handler:
            handler(cheque)
    except Exception as e:
        log.error("Notification error after status change: %s", e, exc_info=True)

    return True, None


def get_available_transitions(cheque, user_role=None):
    """Get all available status transitions for a cheque given the user's role."""
    if user_role is None:
        user_role = current_user.role

    allowed_statuses = VALID_TRANSITIONS.get(cheque.status, [])
    result = []
    for status in allowed_statuses:
        allowed_roles = STATUS_ROLE_PERMISSIONS.get(status, [])
        if user_role in allowed_roles:
            result.append(status)
    return result
