"""
RDC PDC Manager — Audit Log Model
"""
from app.utils import now_ist
from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    __table_args__ = (
        # Compound index for the filter-by-user + filter-by-action dropdowns
        db.Index('ix_audit_logs_user_action', 'user_id', 'action'),
    )

    log_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    table_name = db.Column(db.String(100), nullable=False, index=True)
    record_id = db.Column(db.Integer)
    action = db.Column(db.String(20), nullable=False)  # CREATE / UPDATE / DELETE / STATUS_CHANGE / LOGIN / LOGOUT / ERP_SYNC
    description = db.Column(db.String(500))

    old_values = db.Column(db.Text)  # JSON
    new_values = db.Column(db.Text)  # JSON

    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=now_ist, index=True)

    user = db.relationship('User', backref='audit_logs')

    ACTION_COLORS = {
        'CREATE':        '#10b981',
        'UPDATE':        '#3b82f6',
        'DELETE':        '#ef4444',
        'STATUS_CHANGE': '#8b5cf6',
        'LOGIN':         '#06b6d4',
        'LOGOUT':        '#6b7280',
        'ERP_SYNC':      '#f97316',
    }

    @property
    def action_color(self):
        return self.ACTION_COLORS.get(self.action, '#6b7280')

    def __repr__(self):
        return f'<AuditLog {self.action} on {self.table_name}>'
