"""
RDC PDC Manager — RBAC Decorators
"""
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user, login_required


def role_required(*roles):
    """Restrict access to users with specific roles."""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """Shortcut: restrict access to Admin only."""
    return role_required('Admin')(f)
