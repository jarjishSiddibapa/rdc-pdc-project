"""
RDC PDC Manager — UID Generator Service
Generates unique identifiers for cheques.
Format: PDC-YYYYMMDD-XXXX (sequential per day)
"""
from sqlalchemy import func
from app.extensions import db
from app.models.cheque import Cheque
from app.utils import now_ist


def generate_uid():
    """Generate a unique cheque UID for today (IST date)."""
    today_ist = now_ist()
    today_str = today_ist.strftime('%Y%m%d')

    # Count cheques created today (IST date)
    count = db.session.query(func.count(Cheque.cheque_id)).filter(
        func.date(Cheque.created_at) == today_ist.date()
    ).scalar() or 0

    seq = count + 1
    uid = f"PDC-{today_str}-{str(seq).zfill(4)}"

    # Ensure uniqueness (in case of concurrent access)
    while Cheque.query.filter_by(uid=uid).first():
        seq += 1
        uid = f"PDC-{today_str}-{str(seq).zfill(4)}"

    return uid
