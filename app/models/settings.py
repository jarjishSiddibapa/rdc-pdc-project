"""
RDC PDC Manager — System Settings (Email Config) Model
"""
from app.utils import now_ist
from app.extensions import db


class EmailConfig(db.Model):
    __tablename__ = 'email_config'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    smtp_server = db.Column(db.String(200), nullable=False)
    smtp_port = db.Column(db.Integer, default=587)
    smtp_username = db.Column(db.String(200), nullable=False)
    smtp_password_encrypted = db.Column(db.String(500), nullable=False)
    sender_name = db.Column(db.String(200))
    sender_email = db.Column(db.String(200), nullable=False)
    use_tls = db.Column(db.String(1), default='Y')
    is_active = db.Column(db.String(1), default='Y')
    updated_by = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    updated_at = db.Column(db.DateTime, default=now_ist, onupdate=now_ist)

    updater = db.relationship('User', backref='email_config_updates')

    @property
    def tls_enabled(self):
        return self.use_tls == 'Y'

    def __repr__(self):
        return f'<EmailConfig {self.smtp_server}>'
