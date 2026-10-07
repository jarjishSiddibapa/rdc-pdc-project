"""
RDC PDC Manager — Public Routes (no login required)
Handles publicly accessible share links for cheque images.
"""
import os
from flask import Blueprint, render_template, abort, send_from_directory, current_app

bp = Blueprint('public', __name__, url_prefix='/share')


def _resolve_token(token: str):
    """Return (ChequeShareToken, Cheque) or abort 404."""
    from app.models.share_token import ChequeShareToken
    record = ChequeShareToken.query.filter_by(token=token).first()
    if not record:
        abort(404)
    cheque = record.cheque
    if not cheque or cheque.is_active != 'Y' or not cheque.uploaded_file:
        abort(404)
    return record, cheque


@bp.route('/cheque/<token>')
def view_cheque(token):
    """
    Public cheque image viewer — no authentication required.
    Accessible to anyone with the 32-byte random share link.
    The file itself is served through /share/cheque/<token>/file (below),
    NOT via the unauthenticated /static/uploads/ path.
    """
    _record, cheque = _resolve_token(token)
    return render_template('public/cheque_view.html', cheque=cheque, share_token=token)


@bp.route('/cheque/<token>/file')
def view_cheque_file(token):
    """
    Serve the cheque image file for a valid share token.
    Validates the token before serving — no session required, but
    the file is NOT reachable without a valid token string.
    This replaces the unauthenticated /static/uploads/<filename> path
    for all share-link viewers.
    """
    _record, cheque = _resolve_token(token)
    safe = os.path.basename(cheque.uploaded_file)
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    return send_from_directory(upload_dir, safe)
