"""
RDC PDC Manager — Shared Utilities
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import abort
from flask_login import current_user

IST = ZoneInfo('Asia/Kolkata')


def now_ist() -> datetime:
    """
    Return current date/time in IST as a naive datetime (no tzinfo).
    Use everywhere instead of datetime.utcnow() so all DB timestamps are IST.
    """
    return datetime.now(IST).replace(tzinfo=None)


def check_location_access(cheque) -> None:
    """
    Enforce location-based access for the Accounts role.
    Accounts users can only access cheques in their assigned locations.
    Head-Office users, HO_Accounts, Admin — unrestricted.
    Raises 403 if access is denied.
    """
    if current_user.role == 'Accounts' and not current_user.is_head_office_user:
        allowed = get_user_location_ids(current_user)
        if allowed and cheque.location_id not in allowed:
            abort(403)


def get_user_location_ids(user) -> list:
    """
    Return all location_ids the user is allowed to access.

    Rules:
      - If ANY of the user's linked locations is marked is_head_office='Y'
        → return every active location (Head Office sees everything).
      - Otherwise return the location_ids from the user_locations junction.
      - Fallback: if the junction is empty, use the legacy location_id FK.
      - Empty list means no location restriction was configured yet.
    """
    # Head-Office check
    if user.is_head_office_user:
        from app.models.location import Location
        return [l.location_id for l in Location.query.filter_by(is_active='Y').all()]

    # Multi-location
    lids = [loc.location_id for loc in user.locations]
    if lids:
        return lids

    # Legacy single-location fallback
    if user.location_id:
        return [user.location_id]

    return []
