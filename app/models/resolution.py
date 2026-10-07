"""
RDC PDC Manager — Cheque Resolution Model
"""
from app.utils import now_ist
from app.extensions import db


class ChequeResolution(db.Model):
    __tablename__ = 'cheque_resolution'

    resolution_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cheque_id = db.Column(db.Integer, db.ForeignKey('cheques.cheque_id'), nullable=False, index=True)

    resolution_type = db.Column(db.String(50), nullable=False)
    # LEGAL / NEFT / REDEPLOY

    neft_reference = db.Column(db.String(100))
    remarks        = db.Column(db.String(500))
    uploaded_file  = db.Column(db.String(255))   # mandatory supporting document

    created_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=now_ist)

    creator = db.relationship('User', backref='resolutions_created')

    RESOLUTION_TYPES = [
        ('LEGAL',    'Legal Notice Initiated'),
        ('NEFT',     'NEFT Received'),
        ('REDEPLOY', 'Redeposit Cheque'),
    ]

    @property
    def resolution_type_display(self):
        d = dict(self.RESOLUTION_TYPES)
        return d.get(self.resolution_type, self.resolution_type)

    def __repr__(self):
        return f'<Resolution {self.resolution_type} for cheque_id={self.cheque_id}>'
