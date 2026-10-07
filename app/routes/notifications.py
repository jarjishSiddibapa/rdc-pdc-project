"""
RDC PDC Manager — Notification Routes
"""
import re
from flask import Blueprint, render_template, redirect, url_for, jsonify, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models.notification import Notification
from app.hashids_helper import hid_encode, hid_decode


def _fix_legacy_link(link):
    """
    Rewrite raw-integer cheque links stored before hashid encoding was added.
    e.g.  /cheques/22  →  /cheques/<hashid>
    Any other link is returned unchanged.
    """
    if not link:
        return link
    m = re.match(r'^(/cheques/)(\d+)$', link)
    if m:
        return m.group(1) + hid_encode(int(m.group(2)))
    return link

bp = Blueprint('notifications', __name__, url_prefix='/notifications')


@bp.route('/')
@login_required
def list_notifications():
    """List all notifications for the current user."""
    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    query = Notification.query.filter_by(user_id=current_user.user_id)\
        .order_by(Notification.created_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('notifications/list.html',
                           notifications=pagination.items,
                           pagination=pagination,
                           per_page=per_page)


@bp.route('/mark-read/<hashid:notification_id>', methods=['POST'])
@login_required
def mark_read(notification_id):
    """Mark a single notification as read."""
    notif = Notification.query.get_or_404(notification_id)
    if notif.user_id != current_user.user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    notif.mark_read()
    db.session.commit()

    if notif.link:
        return redirect(_fix_legacy_link(notif.link))
    return redirect(url_for('notifications.list_notifications'))


@bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    """Mark all notifications as read for the current user."""
    Notification.query.filter_by(
        user_id=current_user.user_id, is_read='N'
    ).update({'is_read': 'Y'})
    db.session.commit()

    return jsonify({'success': True})


@bp.route('/mark-bulk-read', methods=['POST'])
@login_required
def mark_bulk_read():
    """Mark a specific set of notifications as read (bulk AJAX action)."""
    data = request.get_json(silent=True) or {}
    raw_ids = data.get('ids', [])

    if not raw_ids or not isinstance(raw_ids, list):
        return jsonify({'ok': False, 'error': 'No IDs provided'}), 400

    # Decode hashids → integers, discard any invalid/missing
    decoded = [hid_decode(str(i)) for i in raw_ids]
    decoded = [i for i in decoded if i is not None]

    if not decoded:
        return jsonify({'ok': False, 'error': 'No valid IDs'}), 400

    updated = Notification.query.filter(
        Notification.notification_id.in_(decoded),
        Notification.user_id == current_user.user_id,
        Notification.is_read == 'N',
    ).update({'is_read': 'Y'}, synchronize_session=False)
    db.session.commit()

    unread_remaining = Notification.query.filter_by(
        user_id=current_user.user_id, is_read='N'
    ).count()

    return jsonify({'ok': True, 'updated': updated, 'unread_remaining': unread_remaining})


@bp.route('/api/count')
@login_required
def unread_count():
    """API: Get unread notification count."""
    count = Notification.query.filter_by(
        user_id=current_user.user_id, is_read='N'
    ).count()
    return jsonify({'count': count})


@bp.route('/api/recent')
@login_required
def recent():
    """API: Get recent notifications for the dropdown."""
    notifications = Notification.query.filter_by(
        user_id=current_user.user_id
    ).order_by(Notification.created_at.desc()).limit(5).all()

    return jsonify([{
        'id': n.notification_id,
        'title': n.title,
        'message': n.message,
        'category': n.category,
        'link': _fix_legacy_link(n.link),
        'is_read': n.is_read,
        'created_at': n.created_at.strftime('%b %d, %H:%M') if n.created_at else '',
    } for n in notifications])
