"""
RDC PDC Manager — Resolution Routes
"""
import os
from app.utils import now_ist
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.cheque import Cheque
from app.models.resolution import ChequeResolution
from app.services.cheque_service import transition_status
from app.services.audit_service import log_action
from app.services import notification_service
from app.decorators import role_required

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.xlsx', '.xls', '.csv'}


def _save_upload(file):
    ext      = os.path.splitext(file.filename)[1].lower()
    filename = secure_filename(f"resolution_{now_ist().strftime('%Y%m%d%H%M%S')}_{file.filename}")
    upload_path = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(upload_path, exist_ok=True)
    file.save(os.path.join(upload_path, filename))
    return filename

bp = Blueprint('resolution', __name__, url_prefix='/resolution')

RESOLUTION_STATUS_MAP = {
    'LEGAL':    'Legal Notice Initiated',
    'NEFT':     'Cleared via NEFT',
    'REDEPLOY': 'Redeposited',
}


@bp.route('/<hashid:cheque_id>/create', methods=['GET', 'POST'])
@role_required('Accounts', 'HO_Accounts')
def create(cheque_id):
    cheque = Cheque.query.get_or_404(cheque_id)

    if cheque.status != 'Bounced':
        flash('Only bounced cheques can be resolved.', 'warning')
        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    if request.method == 'POST':
        resolution_type = request.form.get('resolution_type', '')
        remarks = request.form.get('remarks', '').strip()
        upload  = request.files.get('supporting_doc')

        if resolution_type not in RESOLUTION_STATUS_MAP:
            flash('Please select a valid resolution option.', 'danger')
            return render_template('resolution/form.html', cheque=cheque)

        if not remarks:
            flash('Remarks are required when resolving a bounced cheque.', 'danger')
            return render_template('resolution/form.html', cheque=cheque)

        # Supporting document is mandatory for all resolution types
        if not upload or not upload.filename:
            flash('A supporting document is required.', 'danger')
            return render_template('resolution/form.html', cheque=cheque)

        ext = os.path.splitext(upload.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            flash(f'Unsupported file type "{ext}". Allowed: PDF, images, Excel, CSV.', 'danger')
            return render_template('resolution/form.html', cheque=cheque)

        saved_filename = _save_upload(upload)

        resolution = ChequeResolution(
            cheque_id=cheque.cheque_id,
            resolution_type=resolution_type,
            neft_reference=None,
            remarks=remarks,
            uploaded_file=saved_filename,
            created_by=current_user.user_id,
            created_at=now_ist(),
        )
        db.session.add(resolution)
        db.session.commit()

        target_status = RESOLUTION_STATUS_MAP[resolution_type]
        success, error = transition_status(cheque, target_status, remarks)

        log_action('cheque_resolution', resolution.resolution_id, 'CREATE',
                   description=f"Cheque {cheque.uid} resolved via {resolution.resolution_type_display}")

        # Redeposit notification — the other two (LEGAL, NEFT) are fired
        # inside transition_status via NOTIFICATION_MAP
        try:
            if resolution_type == 'REDEPLOY':
                notification_service.notify_cheque_redeposited(cheque)
            elif resolution_type == 'NEFT':
                notification_service.notify_cheque_neft(cheque)
        except Exception:
            pass

        if success:
            flash(f'Resolution applied: {resolution.resolution_type_display}', 'success')
        else:
            flash(f'Resolution saved but status update failed: {error}', 'warning')

        return redirect(url_for('cheques.detail', cheque_id=cheque_id))

    return render_template('resolution/form.html', cheque=cheque)
