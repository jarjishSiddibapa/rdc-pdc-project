"""
RDC PDC Manager — Reconciliation Model
"""
from app.utils import now_ist
from app.extensions import db


class Reconciliation(db.Model):
    __tablename__ = 'reconciliation'

    recon_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cheque_id = db.Column(db.Integer, db.ForeignKey('cheques.cheque_id'), nullable=False, index=True)

    is_cleared = db.Column(db.String(1), default='N')
    cleared_date = db.Column(db.Date)
    receipt_number = db.Column(db.String(50))
    uploaded_file = db.Column(db.String(255))

    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=now_ist)

    uploader = db.relationship('User', backref='reconciliations')

    def __repr__(self):
        return f'<Reconciliation cheque_id={self.cheque_id}>'
