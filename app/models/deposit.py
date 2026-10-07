"""
RDC PDC Manager — Cheque Deposit Model
"""
from app.utils import now_ist
from app.extensions import db


class ChequeDeposit(db.Model):
    __tablename__ = 'cheque_deposits'

    deposit_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cheque_id = db.Column(db.Integer, db.ForeignKey('cheques.cheque_id'), nullable=False, index=True)

    deposit_number = db.Column(db.String(50))
    deposit_date = db.Column(db.Date, nullable=False)
    deposit_bank = db.Column(db.String(150))
    deposit_branch = db.Column(db.String(150))

    created_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=now_ist)

    creator = db.relationship('User', backref='deposits_created')

    def __repr__(self):
        return f'<Deposit {self.deposit_number}>'
