"""
RDC PDC Manager — ERP Sync Schedule Model
Stores admin-configured sync times. APScheduler loads these on startup
and reloads whenever admin adds/removes a schedule.
"""
from app.utils import now_ist
from app.extensions import db


class ERPSyncSchedule(db.Model):
    __tablename__ = 'erp_sync_schedules'

    schedule_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    hour        = db.Column(db.Integer, nullable=False)   # 0–23 IST
    minute      = db.Column(db.Integer, nullable=False, default=0)  # 0–59
    label       = db.Column(db.String(100))               # optional display name
    is_active   = db.Column(db.String(1), default='Y', nullable=False)
    created_by  = db.Column(db.Integer)
    created_at  = db.Column(db.DateTime, default=now_ist)

    @property
    def time_display(self):
        return f"{self.hour:02d}:{self.minute:02d}"

    def __repr__(self):
        return f'<ERPSyncSchedule {self.time_display}>'
