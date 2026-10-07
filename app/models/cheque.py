"""
RDC PDC Manager — Cheque & Status History Models
"""
from app.utils import now_ist
from app.extensions import db


class Cheque(db.Model):
    __tablename__ = 'cheques'
    __table_args__ = (
        # Composite indexes for the most common query patterns:
        # list with status filter, dashboard aggregations, location-scoped views
        db.Index('ix_cheques_location_status',  'location_id', 'status'),
        db.Index('ix_cheques_customer_id',       'customer_id'),
        db.Index('ix_cheques_salesperson_id',    'salesperson_id'),
        db.Index('ix_cheques_created_by',        'created_by'),
        db.Index('ix_cheques_cheque_date',       'cheque_date'),
        db.Index('ix_cheques_created_at',        'created_at'),
    )

    cheque_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    uid = db.Column(db.String(50), unique=True, nullable=False, index=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.customer_id'), nullable=False)

    cheque_number = db.Column(db.String(50), nullable=False)
    cheque_date = db.Column(db.Date, nullable=False)
    bank_name = db.Column(db.String(150))
    bank_id = db.Column(db.Integer, db.ForeignKey('banks.bank_id'))
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(10), default='INR')
    cheque_type = db.Column(db.String(50), default='PDC')  # PDC / Open

    status = db.Column(db.String(50), default='Pending with Customer', nullable=False, index=True)
    lying_with = db.Column(db.String(50), default='Customer')

    uploaded_file = db.Column(db.String(255))
    remarks = db.Column(db.String(500))

    received_date = db.Column(db.Date)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    salesperson_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    location_id = db.Column(db.Integer, db.ForeignKey('locations.location_id'))

    created_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=now_ist)
    updated_by = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime, onupdate=now_ist)

    is_active = db.Column(db.String(1), default='Y', nullable=False)

    # Relationships
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_cheques')
    assignee = db.relationship('User', foreign_keys=[assigned_to], backref='assigned_cheques')
    salesperson = db.relationship('User', foreign_keys=[salesperson_id], backref='sales_cheques')
    bank = db.relationship('Bank', backref='cheques')
    location = db.relationship('Location', backref='cheques')
    status_history = db.relationship('ChequeStatusHistory', backref='cheque', lazy='dynamic',
                                     order_by='ChequeStatusHistory.updated_at.desc()')
    deposits = db.relationship('ChequeDeposit', backref='cheque', lazy='dynamic')
    reconciliation = db.relationship('Reconciliation', backref='cheque', uselist=False)
    resolutions = db.relationship('ChequeResolution', backref='cheque', lazy='dynamic')

    # Status constants
    STATUS_PENDING = 'Pending with Customer'
    STATUS_COLLECTED = 'Collected by Sales Person'
    STATUS_ACCEPTED = 'Accepted'
    STATUS_REJECTED = 'Rejected'
    STATUS_DEPOSITED = 'Deposited'
    STATUS_CLEARED = 'Cleared'
    STATUS_BOUNCED = 'Bounced'
    STATUS_RESOLVED = 'Resolved'  # legacy — kept for existing records
    STATUS_LEGAL = 'Legal Notice Initiated'
    STATUS_NEFT = 'Cleared via NEFT'
    STATUS_NEW_CHEQUE      = 'New Cheque Received'  # Customer gives new cheque — terminal
    STATUS_NEFT_RECEIVED   = 'NEFT Received'        # Sales reports NEFT received; CC confirms
    STATUS_ORDER_CANCELLED = 'Order Cancelled'      # Order cancelled — terminal
    STATUS_REDEPOSITED     = 'Redeposited'          # Bounced → redeposit; awaiting fresh deposit

    ALL_STATUSES = [
        STATUS_PENDING, STATUS_COLLECTED, STATUS_ACCEPTED, STATUS_REJECTED,
        STATUS_DEPOSITED, STATUS_CLEARED, STATUS_BOUNCED,
        STATUS_LEGAL, STATUS_NEFT,
        STATUS_NEW_CHEQUE, STATUS_NEFT_RECEIVED, STATUS_ORDER_CANCELLED,
        STATUS_REDEPOSITED, STATUS_RESOLVED,
    ]

    STATUS_COLORS = {
        'Pending with Customer':    '#f97316',
        'Collected by Sales Person': '#3b82f6',
        'Accepted':                 '#6366f1',
        'Rejected':                 '#6b7280',
        'Deposited':                '#8b5cf6',
        'Cleared':                  '#10b981',
        'Bounced':                  '#ef4444',
        'Legal Notice Initiated':   '#991b1b',
        'Cleared via NEFT':         '#059669',
        'New Cheque Received':      '#f97316',
        'NEFT Received':            '#3b82f6',
        'Order Cancelled':          '#6b7280',
        'Redeposited':              '#f59e0b',
        'Resolved':                 '#14b8a6',
    }

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, '#6b7280')

    @property
    def amount_display(self):
        return f"₹{self.amount:,.2f}"

    def __repr__(self):
        return f'<Cheque {self.uid}>'


class ChequeStatusHistory(db.Model):
    __tablename__ = 'cheque_status_history'

    history_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cheque_id = db.Column(db.Integer, db.ForeignKey('cheques.cheque_id'), nullable=False, index=True)

    old_status = db.Column(db.String(50))
    new_status = db.Column(db.String(50), nullable=False)
    old_lying_with = db.Column(db.String(50))
    new_lying_with = db.Column(db.String(50))

    remarks = db.Column(db.String(500))

    updated_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    updated_at = db.Column(db.DateTime, default=now_ist)

    updater = db.relationship('User', backref='status_updates')

    def __repr__(self):
        return f'<StatusHistory {self.old_status} → {self.new_status}>'
