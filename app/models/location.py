"""
RDC PDC Manager — Location Master Model
"""
from app.utils import now_ist
from app.extensions import db


class Location(db.Model):
    __tablename__ = 'locations'

    location_id    = db.Column(db.Integer, primary_key=True, autoincrement=True)
    location_name  = db.Column(db.String(150), nullable=False)
    is_head_office = db.Column(db.String(1), default='N', nullable=False)
    is_active      = db.Column(db.String(1), default='Y', nullable=False)
    created_at     = db.Column(db.DateTime, default=now_ist)

    @property
    def display_name(self):
        label = self.location_name
        if self.is_head_office == 'Y':
            label += " ★"
        return label

    def __repr__(self):
        return f'<Location {self.location_name}>'
