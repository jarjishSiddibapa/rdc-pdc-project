"""
RDC PDC Manager — Notification Model
"""
from app.utils import now_ist
from app.extensions import db


class Notification(db.Model):
    __tablename__ = 'notifications'
    __table_args__ = (
        # Compound index: every unread-count and recent-notifications query
        # filters on both user_id AND is_read simultaneously.
        db.Index('ix_notifications_user_is_read', 'user_id', 'is_read'),
    )

    notification_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)

    title = db.Column(db.String(200))
    message = db.Column(db.String(500), nullable=False)
    link = db.Column(db.String(255))  # URL to navigate to
    category = db.Column(db.String(50), default='info')  # info, success, warning, danger

    is_read = db.Column(db.String(1), default='N')
    created_at = db.Column(db.DateTime, default=now_ist)

    @property
    def read(self):
        return self.is_read == 'Y'

    def mark_read(self):
        self.is_read = 'Y'

    def __repr__(self):
        return f'<Notification {self.notification_id} for user {self.user_id}>'
