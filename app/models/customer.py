"""
RDC PDC Manager — Customer Model
"""
from datetime import datetime
from app.utils import now_ist
from app.extensions import db


class Customer(db.Model):
    __tablename__ = 'customers'

    customer_id    = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_code  = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_name  = db.Column(db.String(200), nullable=False)
    contact_person = db.Column(db.String(150))
    contact_phone  = db.Column(db.String(20))
    contact_email  = db.Column(db.String(150))
    address        = db.Column(db.Text)
    city           = db.Column(db.String(100))
    gst_number     = db.Column(db.String(20))
    erp_customer_id = db.Column(db.String(50), index=True)    # Oracle ERP ACCOUNT_NUMBER
    salesperson_id  = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)
    is_active      = db.Column(db.String(1), default='Y', nullable=False)
    created_by     = db.Column(db.Integer)
    created_at     = db.Column(db.DateTime, default=now_ist)
    updated_at     = db.Column(db.DateTime, onupdate=now_ist)

    # ── Relationships ─────────────────────────────────────────────────────────
    cheques     = db.relationship('Cheque', backref='customer', lazy='dynamic')
    salesperson = db.relationship('User', foreign_keys=[salesperson_id], backref='owned_customers')

    # Many-to-many: locations this customer is associated with
    locations = db.relationship(
        'Location',
        secondary='customer_locations',
        backref=db.backref('customer_members', lazy='dynamic'),
        lazy='subquery',
    )

    @property
    def active(self):
        return self.is_active == 'Y'

    @property
    def locations_display(self) -> str:
        names = [loc.location_name for loc in self.locations]
        return ', '.join(names) if names else (self.city or '—')

    def __repr__(self):
        return f'<Customer {self.customer_code} - {self.customer_name}>'
