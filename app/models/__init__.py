"""
RDC PDC Manager — Models Package
Import all models here so SQLAlchemy registers them.
associations must be imported AFTER Location, User, Customer so the FK targets exist.
"""
from app.models.location import Location
from app.models.user import User
from app.models.customer import Customer
from app.models.associations import user_locations, customer_locations   # junction tables
from app.models.cheque import Cheque, ChequeStatusHistory
from app.models.deposit import ChequeDeposit
from app.models.reconciliation import Reconciliation
from app.models.resolution import ChequeResolution
from app.models.notification import Notification
from app.models.audit import AuditLog
from app.models.bank import Bank
from app.models.settings import EmailConfig
from app.models.erp_schedule import ERPSyncSchedule
from app.models.password_reset import PasswordResetToken
from app.models.share_token import ChequeShareToken

__all__ = [
    'Location', 'User', 'Customer',
    'user_locations', 'customer_locations',
    'Cheque', 'ChequeStatusHistory',
    'ChequeDeposit', 'Reconciliation', 'ChequeResolution',
    'Notification', 'AuditLog', 'Bank', 'EmailConfig', 'ERPSyncSchedule',
    'PasswordResetToken', 'ChequeShareToken',
]
