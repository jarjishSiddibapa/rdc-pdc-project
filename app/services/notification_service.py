"""
RDC PDC Manager — Notification Service
Creates in-app notifications and sends email alerts for every workflow action.
Location-aware: Accounts/Sales notifications are scoped to the cheque's location.
"""
import logging
from app.utils import now_ist
from app.extensions import db
from app.models.notification import Notification
from app.models.user import User
from app.services.email_service import send_email, get_email_config
from app.hashids_helper import hid_encode
from sqlalchemy.orm import joinedload

log = logging.getLogger(__name__)


def _cheque_link(cheque):
    """Return the hashid-encoded URL for a cheque detail page."""
    return f"/cheques/{hid_encode(cheque.cheque_id)}"


# ── Core primitives ───────────────────────────────────────────────────────────

def create_notification(user_id, title, message, link=None, category='info'):
    notif = Notification(
        user_id=user_id, title=title, message=message,
        link=link, category=category, created_at=now_ist(),
    )
    db.session.add(notif)
    db.session.commit()
    return notif


def notify_user(user_id, title, message, link=None, category='info',
                send_mail=True, _user=None):
    """
    In-app notification + optional email for a single user.

    Pass `_user` (a pre-fetched User ORM object) to avoid a redundant
    SELECT when the caller already has the object in hand.
    """
    create_notification(user_id, title, message, link, category)
    if send_mail:
        # Use the pre-fetched object if provided; only hit the DB as fallback.
        user = _user or db.session.get(User, user_id)
        if user and user.email and get_email_config():
            send_email(user.email, f"RDC PDC — {title}",
                       _build_email_html(title, message, link))


def notify_role(role, title, message, link=None, category='info', send_mail=True):
    """Notify ALL active users with a given role (no location filter)."""
    users = (User.query
             .filter_by(role=role, _is_active='Y')
             .options(joinedload(User.locations))
             .all())
    for user in users:
        notify_user(user.user_id, title, message, link, category, send_mail, _user=user)


def notify_location_role(role, location_id, title, message,
                         link=None, category='info', send_mail=True):
    """
    Notify active users of a role who are linked to the given location.
    Multi-location aware: checks the user_locations junction table.
    Head-Office users always receive the alert regardless of location.
    If location_id is None, notifies ALL active users of that role.

    Uses joinedload to fetch user.locations in a single query, avoiding
    N+1 SELECT per user.
    """
    users = (User.query
             .filter_by(role=role, _is_active='Y')
             .options(joinedload(User.locations))
             .all())

    if location_id:
        # Build a set of location_ids per user in Python — no extra queries
        # because locations are already eager-loaded above.
        target_users = [
            u for u in users
            if u.is_head_office_user
            or location_id in {loc.location_id for loc in u.locations}
        ]
    else:
        target_users = users

    for user in target_users:
        notify_user(user.user_id, title, message, link, category, send_mail, _user=user)


# ── Cheque workflow notifications ─────────────────────────────────────────────

def notify_cheque_created(cheque):
    """New cheque submitted → notify Accounts in same location."""
    notify_location_role(
        'Accounts', cheque.location_id,
        'New Cheque Submitted',
        f"Cheque {cheque.uid} for {cheque.customer.customer_name} "
        f"(₹{cheque.amount:,.2f}) awaits your review.",
        link=_cheque_link(cheque), category='info',
    )


def notify_cheque_collected(cheque):
    """Sales collected the cheque → notify Accounts in same location."""
    title = 'Cheque Collected — Pending Approval'
    msg = (f"Cheque {cheque.uid} for {cheque.customer.customer_name} "
           f"(₹{cheque.amount:,.2f}) has been collected and is awaiting acceptance.")
    link = _cheque_link(cheque)
    notify_location_role('Accounts', cheque.location_id, title, msg, link=link, category='info')


def notify_cheque_accepted(cheque):
    """Accounts accepted → notify the Sales person who created it."""
    notify_user(
        cheque.created_by,
        'Cheque Accepted ✓',
        f"Your cheque {cheque.uid} for {cheque.customer.customer_name} "
        f"(₹{cheque.amount:,.2f}) has been accepted by Accounts.",
        link=_cheque_link(cheque), category='success',
    )


def notify_cheque_rejected(cheque, reason=''):
    """Accounts rejected → notify the Sales person."""
    msg = (f"Your cheque {cheque.uid} for {cheque.customer.customer_name} "
           f"(₹{cheque.amount:,.2f}) was rejected by Accounts.")
    if reason:
        msg += f" Reason: {reason}"
    notify_user(
        cheque.created_by, 'Cheque Rejected ✗', msg,
        link=_cheque_link(cheque), category='warning',
    )


def notify_cheque_deposited(cheque):
    """Accounts deposited → notify HO Accounts + Sales creator."""
    msg = (f"Cheque {cheque.uid} for {cheque.customer.customer_name} "
           f"(₹{cheque.amount:,.2f}) has been deposited.")
    link = _cheque_link(cheque)
    notify_role('HO_Accounts', 'Cheque Deposited — Awaiting Reconciliation',
                msg + ' Please reconcile.', link=link, category='info')
    notify_user(cheque.created_by, 'Cheque Deposited ✓',
                msg, link=link, category='info')


def notify_cheque_cleared(cheque):
    """HO reconciled as Cleared → notify Sales + location Accounts."""
    msg = (f"Cheque {cheque.uid} for {cheque.customer.customer_name} "
           f"(₹{cheque.amount:,.2f}) has been CLEARED by the bank.")
    notify_user(cheque.created_by, 'Cheque Cleared ✓', msg,
                link=_cheque_link(cheque), category='success')
    notify_location_role('Accounts', cheque.location_id,
                         'Cheque Cleared ✓', msg,
                         link=_cheque_link(cheque), category='success')


def notify_cheque_bounced(cheque):
    """Reconciled as Bounced → notify Accounts + HO_Accounts + Sales."""
    msg = (f"ALERT: Cheque {cheque.uid} for {cheque.customer.customer_name} "
           f"(₹{cheque.amount:,.2f}) has BOUNCED. Immediate action required.")
    link = _cheque_link(cheque)
    notify_role('HO_Accounts', 'Cheque Bounced ⚠', msg, link=link, category='danger')
    notify_location_role('Accounts', cheque.location_id,
                         'Cheque Bounced ⚠', msg, link=link, category='danger')
    notify_user(cheque.created_by, 'Cheque Bounced ⚠', msg, link=link, category='danger')


def notify_cheque_legal(cheque):
    """Credit Control / HO initiated legal → notify Accounts + HO + Sales creator."""
    msg = (f"Legal Notice has been initiated for bounced cheque {cheque.uid} "
           f"({cheque.customer.customer_name}, ₹{cheque.amount:,.2f}).")
    link = _cheque_link(cheque)
    notify_location_role('Accounts', cheque.location_id,
                         'Legal Notice Initiated', msg, link=link, category='danger')
    notify_role('HO_Accounts', 'Legal Notice Initiated', msg, link=link, category='danger')
    notify_user(cheque.created_by, 'Legal Notice Initiated', msg, link=link, category='danger')


def notify_cheque_neft(cheque):
    """Credit Control / HO recorded NEFT → notify Accounts + HO + Sales creator."""
    msg = (f"Bounced cheque {cheque.uid} ({cheque.customer.customer_name}, "
           f"₹{cheque.amount:,.2f}) has been cleared via NEFT.")
    link = _cheque_link(cheque)
    notify_location_role('Accounts', cheque.location_id,
                         'Cleared via NEFT ✓', msg, link=link, category='success')
    notify_role('HO_Accounts', 'Cleared via NEFT ✓', msg, link=link, category='success')
    notify_user(cheque.created_by, 'Cleared via NEFT ✓', msg, link=link, category='success')


def notify_cheque_new_cheque_received(cheque):
    """Customer gave a new cheque — notify location Accounts."""
    msg = (f"Cheque {cheque.uid} ({cheque.customer.customer_name}, ₹{cheque.amount:,.2f}) "
           f"has been closed — a new cheque has been received from the customer.")
    notify_user(cheque.created_by, 'New Cheque Received', msg,
                link=_cheque_link(cheque), category='info')
    notify_location_role('Accounts', cheque.location_id,
                         'New Cheque Received', msg,
                         link=_cheque_link(cheque), category='info')


def notify_cheque_neft_received(cheque):
    """Sales reported NEFT received — notify Accounts to confirm."""
    msg = (f"Sales has reported NEFT received for cheque {cheque.uid} "
           f"({cheque.customer.customer_name}, ₹{cheque.amount:,.2f}). "
           f"Please verify and confirm.")
    notify_role('Accounts', 'NEFT Received — Confirmation Required', msg,
                link=_cheque_link(cheque), category='info')


def notify_cheque_redeposited(cheque):
    """Redeposited → notify location Accounts + HO_Accounts + Sales creator."""
    msg = (f"Bounced cheque {cheque.uid} ({cheque.customer.customer_name}, "
           f"₹{cheque.amount:,.2f}) has been marked for redeposit and is ready for re-deposit.")
    link = _cheque_link(cheque)
    notify_location_role('Accounts', cheque.location_id,
                         'Cheque Redeposited — Pending Re-deposit',
                         msg, link=link, category='info')
    notify_role('HO_Accounts', 'Cheque Redeposited — Pending Re-deposit',
                msg, link=link, category='info')
    notify_user(cheque.created_by, 'Cheque Redeposited',
                msg, link=link, category='info')


# ── ERP sync notification ─────────────────────────────────────────────────────

def notify_erp_sync_done(result, triggered_by=None):
    """Notify Admin(s) when a scheduled ERP sync completes."""
    msg = (f"ERP sync complete — "
           f"{result['cust_created']} customers created, "
           f"{result['cust_updated']} updated, "
           f"{result['user_created']} salesreps created"
           + (f" | {len(result['errors'])} error(s)" if result['errors'] else '') + ".")
    for user in User.query.filter_by(role='Admin', _is_active='Y').all():
        notify_user(user.user_id, 'ERP Sync Completed', msg,
                    link='/erp-sync/', category='info', _user=user)


# ── Email HTML builder ────────────────────────────────────────────────────────

def _build_email_html(title, message, link=None):
    link_html = ''
    if link:
        from flask import request as _req
        try:
            base = _req.host_url.rstrip('/')
        except RuntimeError:
            base = 'http://localhost:50001'
        abs_link = f"{base}{link}"
        link_html = f'''
        <div style="text-align:center;margin-top:24px;">
            <a href="{abs_link}"
               style="background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;
                      padding:12px 32px;border-radius:8px;text-decoration:none;
                      font-weight:600;display:inline-block;">View Details</a>
        </div>'''

    return f'''
    <div style="max-width:600px;margin:0 auto;font-family:'Segoe UI',Arial,sans-serif;">
        <div style="background:linear-gradient(135deg,#1e1b4b,#312e81);
                    padding:24px 32px;border-radius:12px 12px 0 0;">
            <h1 style="color:white;margin:0;font-size:20px;">🔔 {title}</h1>
            <p style="color:#a5b4fc;margin:6px 0 0;font-size:13px;">RDC PDC Manager</p>
        </div>
        <div style="background:#ffffff;padding:32px;border:1px solid #e2e8f0;
                    border-top:none;border-radius:0 0 12px 12px;">
            <p style="color:#334155;font-size:15px;line-height:1.6;margin:0;">{message}</p>
            {link_html}
        </div>
        <div style="text-align:center;padding:16px;color:#94a3b8;font-size:12px;">
            RDC PDC Manager — Automated Notification
        </div>
    </div>'''
