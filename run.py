"""
RDC PDC Manager — Application Entry Point
Run this file to start the development server.
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=50001, debug=True)
