"""
RDC PDC Manager — Bank Master Model
"""
from app.utils import now_ist
from app.extensions import db


class Bank(db.Model):
    __tablename__ = 'banks'

    bank_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    bank_name = db.Column(db.String(150), nullable=False)
    is_active = db.Column(db.String(1), default='Y', nullable=False)
    created_at = db.Column(db.DateTime, default=now_ist)

    @property
    def display_name(self):
        return self.bank_name

    def __repr__(self):
        return f'<Bank {self.bank_name}>'
