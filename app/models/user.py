"""
RDC PDC Manager — User Model
"""
import random
from datetime import datetime
from app.utils import now_ist
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    user_id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username        = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash   = db.Column(db.String(255), nullable=False)
    full_name       = db.Column(db.String(150), nullable=False)
    role            = db.Column(db.String(50), nullable=False)
    email           = db.Column(db.String(150))
    phone           = db.Column(db.String(20))
    location        = db.Column(db.String(100))   # legacy string field — kept for compat
    location_id     = db.Column(db.Integer, db.ForeignKey('locations.location_id'), nullable=True)
    sales_person_id = db.Column(db.String(50))    # ERP SALESREP_NUMBER (string)
    salesrep_id     = db.Column(db.Integer)        # ERP SALESREP_ID (numeric Oracle PK)
    _is_active      = db.Column('is_active', db.String(1), default='Y', nullable=False)
    avatar_color    = db.Column(db.String(7))
    profile_picture = db.Column(db.String(255))
    last_login      = db.Column(db.DateTime)
    created_at      = db.Column(db.DateTime, default=now_ist)
    created_by      = db.Column(db.Integer)
    updated_at      = db.Column(db.DateTime, onupdate=now_ist)
    updated_by      = db.Column(db.Integer)

    # ── Relationships ─────────────────────────────────────────────────────────
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    user_location = db.relationship('Location', foreign_keys=[location_id])

    # Many-to-many: all locations this user can access
    locations = db.relationship(
        'Location',
        secondary='user_locations',
        backref=db.backref('user_members', lazy='dynamic'),
        lazy='subquery',
    )

    ROLE_CHOICES = ['Admin', 'Sales', 'Accounts', 'HO_Accounts']
    ROLE_DISPLAY = {
        'Admin':       'Admin',
        'Sales':       'Sales Person',
        'Accounts':    'Accounts',
        'HO_Accounts': 'HO Accounts',
    }
    AVATAR_COLORS = [
        '#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f97316',
        '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
    ]

    # ── Flask-Login ───────────────────────────────────────────────────────────

    def get_id(self):
        return str(self.user_id)

    @property
    def is_active(self):
        return self._is_active == 'Y'

    @is_active.setter
    def is_active(self, value):
        if isinstance(value, bool):
            self._is_active = 'Y' if value else 'N'
        else:
            self._is_active = value

    # ── Auth ──────────────────────────────────────────────────────────────────

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256:600000')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ── Location helpers ──────────────────────────────────────────────────────

    @property
    def is_head_office_user(self) -> bool:
        """True if any of the user's linked locations is the Head Office."""
        return any(loc.is_head_office == 'Y' for loc in self.locations)

    @property
    def accessible_location_ids(self) -> list:
        """
        Returns ALL location IDs this user can access.
        - Head Office users → every active location (see everything)
        - Others → their assigned locations list
        - Fallback → primary location_id (legacy)
        """
        if self.is_head_office_user:
            from app.models.location import Location as Loc
            return [l.location_id for l in Loc.query.filter_by(is_active='Y').all()]
        lids = [loc.location_id for loc in self.locations]
        if not lids and self.location_id:
            lids = [self.location_id]
        return lids

    # ── Display helpers ───────────────────────────────────────────────────────

    @property
    def role_display(self):
        return self.ROLE_DISPLAY.get(self.role, self.role)

    @property
    def initials(self):
        parts = self.full_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.full_name[:2].upper()

    @property
    def locations_display(self) -> str:
        """Comma-joined location names for display."""
        names = [loc.location_name for loc in self.locations]
        return ', '.join(names) if names else (self.user_location.location_name if self.user_location else '—')

    @staticmethod
    def generate_avatar_color():
        return random.choice(User.AVATAR_COLORS)

    @property
    def unread_notification_count(self):
        return self.notifications.filter_by(is_read='N').count()

    def __repr__(self):
        return f'<User {self.username}>'
