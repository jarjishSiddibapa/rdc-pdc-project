"""
RDC PDC Manager — Password Reset Token Model
Stores short-lived, single-use tokens for the forgot-password flow.
The plaintext token is NEVER stored — only its SHA-256 hash.
"""
import hashlib
import secrets
from datetime import timedelta

from app.extensions import db
from app.utils import now_ist

TOKEN_EXPIRY_HOURS = 1


class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.user_id'),
                           nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used       = db.Column(db.String(1), default='N', nullable=False)
    created_at = db.Column(db.DateTime, default=now_ist)

    user = db.relationship('User', backref=db.backref('reset_tokens', lazy='dynamic'))

    # ── Factory ───────────────────────────────────────────────────────────────

    @staticmethod
    def generate_for(user):
        """
        Invalidate any existing unused tokens for this user, then create a
        fresh one.  Returns the **plaintext** token (32-byte URL-safe string)
        which must be embedded in the email link and never stored.
        """
        # Burn old tokens so only the newest link works
        PasswordResetToken.query.filter_by(
            user_id=user.user_id, used='N'
        ).update({'used': 'Y'})

        plaintext  = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()

        record = PasswordResetToken(
            user_id    = user.user_id,
            token_hash = token_hash,
            expires_at = now_ist() + timedelta(hours=TOKEN_EXPIRY_HOURS),
        )
        db.session.add(record)
        db.session.commit()
        return plaintext   # ← sent in email URL, never saved to DB

    # ── Lookup ────────────────────────────────────────────────────────────────

    @staticmethod
    def verify(plaintext_token):
        """
        Verify a plaintext token received from the URL.
        Returns (PasswordResetToken | None, error_message | None).
        """
        token_hash = hashlib.sha256(plaintext_token.encode()).hexdigest()
        record = PasswordResetToken.query.filter_by(
            token_hash=token_hash, used='N'
        ).first()

        if not record:
            return None, 'This reset link is invalid or has already been used.'
        if record.expires_at < now_ist():
            record.used = 'Y'
            db.session.commit()
            return None, 'This reset link has expired. Please request a new one.'

        return record, None

    def consume(self):
        """Mark token as used (call after the password has been changed)."""
        self.used = 'Y'
        db.session.commit()
