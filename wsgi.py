"""
RDC PDC Manager — WSGI Entry Point
Use this file for production deployment with Gunicorn/Waitress.
Example: gunicorn wsgi:app -w 4 -b 0.0.0.0:5000
"""
from app import create_app

app = create_app()
