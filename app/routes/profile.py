"""
RDC PDC Manager — User Profile Routes
"""
import os
from app.utils import now_ist
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import func
from app.extensions import db
from app.models.user import User
from app.models.cheque import Cheque
from app.services.audit_service import log_action

bp = Blueprint('profile', __name__, url_prefix='/profile')

ALLOWED_IMG = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_IMG_BYTES = 5 * 1024 * 1024  # 5 MB


def _allowed_img(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMG


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        action = request.form.get('action')

        # ── Update personal details ───────────────────────────────────────────
        if action == 'update_profile':
            full_name = request.form.get('full_name', '').strip()
            email     = request.form.get('email', '').strip() or None
            phone     = request.form.get('phone', '').strip() or None

            if not full_name:
                flash('Display name cannot be empty.', 'danger')
                return redirect(url_for('profile.index'))

            current_user.full_name = full_name
            current_user.email     = email
            current_user.phone     = phone
            current_user.updated_at = now_ist()
            db.session.commit()
            log_action('users', current_user.user_id, 'UPDATE',
                       description=f"{current_user.username} updated their profile")
            flash('Profile updated successfully.', 'success')

        # ── Upload profile picture ────────────────────────────────────────────
        elif action == 'upload_picture':
            file = request.files.get('profile_picture')
            if not file or not file.filename:
                flash('No file selected.', 'warning')
                return redirect(url_for('profile.index'))
            if not _allowed_img(file.filename):
                flash('Unsupported file type. Use PNG, JPG, GIF or WebP.', 'danger')
                return redirect(url_for('profile.index'))
            # Size check
            file.seek(0, 2)
            size = file.tell()
            file.seek(0)
            if size > MAX_IMG_BYTES:
                flash('File too large — maximum 5 MB.', 'danger')
                return redirect(url_for('profile.index'))

            # Delete old avatar file if it exists
            if current_user.profile_picture:
                old_path = os.path.join(current_app.root_path, 'static', 'uploads',
                                        current_user.profile_picture)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass

            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"avatar_{current_user.user_id}_{now_ist().strftime('%Y%m%d%H%M%S')}.{ext}"
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_path, exist_ok=True)
            file.save(os.path.join(upload_path, filename))
            current_user.profile_picture = filename
            current_user.updated_at = now_ist()
            db.session.commit()
            log_action('users', current_user.user_id, 'UPDATE',
                       description=f"{current_user.username} updated their profile picture")
            flash('Profile picture updated.', 'success')

        # ── Remove picture ────────────────────────────────────────────────────
        elif action == 'remove_picture':
            if current_user.profile_picture:
                old_path = os.path.join(current_app.root_path, 'static', 'uploads',
                                        current_user.profile_picture)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
            current_user.profile_picture = None
            current_user.updated_at = now_ist()
            db.session.commit()
            log_action('users', current_user.user_id, 'UPDATE',
                       description=f"{current_user.username} removed their profile picture")
            flash('Profile picture removed.', 'info')

        # ── Set avatar colour ─────────────────────────────────────────────────
        elif action == 'set_avatar_color':
            color = request.form.get('color', '').strip()
            if color and color.startswith('#') and len(color) in (4, 7):
                current_user.avatar_color = color
                current_user.updated_at = now_ist()
                db.session.commit()
            flash('Avatar colour updated.', 'success')

        # ── Change password ───────────────────────────────────────────────────
        elif action == 'change_password':
            current_pw  = request.form.get('current_password', '')
            new_pw      = request.form.get('new_password', '')
            confirm_pw  = request.form.get('confirm_password', '')

            if not current_user.check_password(current_pw):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('profile.index'))
            if len(new_pw) < 8:
                flash('New password must be at least 8 characters.', 'danger')
                return redirect(url_for('profile.index'))
            if new_pw != confirm_pw:
                flash('Passwords do not match.', 'danger')
                return redirect(url_for('profile.index'))
            if current_pw == new_pw:
                flash('New password must be different from the current password.', 'warning')
                return redirect(url_for('profile.index'))

            current_user.set_password(new_pw)
            current_user.updated_at = now_ist()
            db.session.commit()
            log_action('users', current_user.user_id, 'UPDATE',
                       description=f"{current_user.username} changed their password")
            flash('Password changed successfully.', 'success')

        return redirect(url_for('profile.index'))

    # ── GET — gather stats ────────────────────────────────────────────────────
    stats = db.session.query(
        func.count(Cheque.cheque_id).label('total'),
        func.coalesce(func.sum(Cheque.amount), 0).label('total_amount'),
    ).filter(
        Cheque.is_active == 'Y',
        Cheque.created_by == current_user.user_id,
    ).one()

    return render_template('profile/index.html',
                           stats=stats,
                           avatar_colors=User.AVATAR_COLORS)


@bp.route('/roles')
@login_required
def roles():
    return render_template('profile/roles.html')
