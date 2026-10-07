"""
RDC PDC Manager — Many-to-Many Association Tables
Defined here (not in individual models) to avoid circular imports.
"""
from app.extensions import db

# Users ↔ Locations  (a user can serve multiple locations)
user_locations = db.Table(
    'user_locations',
    db.Column('user_id',     db.Integer, db.ForeignKey('users.user_id',     ondelete='CASCADE'), primary_key=True),
    db.Column('location_id', db.Integer, db.ForeignKey('locations.location_id', ondelete='CASCADE'), primary_key=True),
)

# Customers ↔ Locations  (a customer can have sites in multiple locations)
customer_locations = db.Table(
    'customer_locations',
    db.Column('customer_id', db.Integer, db.ForeignKey('customers.customer_id', ondelete='CASCADE'), primary_key=True),
    db.Column('location_id', db.Integer, db.ForeignKey('locations.location_id', ondelete='CASCADE'), primary_key=True),
)
