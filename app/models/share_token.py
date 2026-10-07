"""
RDC PDC Manager — Cheque Share Token Model
Generates unguessable, permanent public share links for cheque images.
The token gives read-only access to the cheque image + minimal info.
No login is required to follow a share link.
"""
import secrets
from app.extensions import db
from app.utils import now_ist


class ChequeShareToken(db.Model):
    __tablename__ = 'cheque_share_tokens'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cheque_id  = db.Column(db.Integer, db.ForeignKey('cheques.cheque_id'),
                           nullable=False, unique=True, index=True)
    token      = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=now_ist)

    cheque  = db.relationship('Cheque',
                              backref=db.backref('share_token', uselist=False))
    creator = db.relationship('User', foreign_keys=[created_by])

    @staticmethod
    def get_or_create(cheque_id: int, user_id: int) -> 'ChequeShareToken':
        """Return existing share token for the cheque, or create a fresh one."""
        existing = ChequeShareToken.query.filter_by(cheque_id=cheque_id).first()
        if existing:
            return existing
        record = ChequeShareToken(
            cheque_id  = cheque_id,
            token      = secrets.token_urlsafe(32),
            created_by = user_id,
        )
        db.session.add(record)
        db.session.commit()
        return record
