"""
RDC PDC Manager — Audit Service
Logs every significant action in the system.
"""
import json
import logging
from app.utils import now_ist
from flask import request
from flask_login import current_user
from app.extensions import db
from app.models.audit import AuditLog

log = logging.getLogger(__name__)


def log_action(table_name, record_id, action, description=None,
               old_values=None, new_values=None):
    """
    Create an audit log entry.

    Args:
        table_name: Name of the affected table
        record_id: Primary key of the affected record
        action: CREATE / UPDATE / DELETE / STATUS_CHANGE / LOGIN / LOGOUT
        description: Human-readable description
        old_values: Dict of old field values (for updates)
        new_values: Dict of new field values
    """
    try:
        # NOTE: local var is named `entry` (not `log`) to avoid shadowing the
        # module-level logger, which would break the except-block error logging.
        entry = AuditLog(
            table_name=table_name,
            record_id=record_id,
            action=action,
            description=description,
            old_values=json.dumps(old_values, default=str) if old_values else None,
            new_values=json.dumps(new_values, default=str) if new_values else None,
            user_id=current_user.user_id if current_user and current_user.is_authenticated else None,
            ip_address=request.remote_addr if request else None,
            created_at=now_ist(),
        )
        db.session.add(entry)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    except Exception as e:
        log.error("Failed to log audit action: %s", e, exc_info=True)
