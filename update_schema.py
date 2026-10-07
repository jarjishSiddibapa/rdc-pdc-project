from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    # 1. Create any missing tables (e.g., the new 'locations' table)
    db.create_all()
    print("Checked and created missing tables (like 'locations').")

    # 2. Add the new columns to the existing 'cheques' table
    with db.engine.begin() as conn:
        print("Applying ALTER TABLE statements to 'cheques'...")
        
        try:
            conn.execute(text("ALTER TABLE cheques ADD COLUMN bank_id INT;"))
            print(" - Added 'bank_id' column.")
        except Exception as e:
            print(" - 'bank_id' already exists or error:", str(e).split('\n')[0])

        try:
            conn.execute(text("ALTER TABLE cheques ADD COLUMN salesperson_id INT;"))
            print(" - Added 'salesperson_id' column.")
        except Exception as e:
            print(" - 'salesperson_id' already exists or error:", str(e).split('\n')[0])

        try:
            conn.execute(text("ALTER TABLE cheques ADD COLUMN location_id INT;"))
            print(" - Added 'location_id' column.")
        except Exception as e:
            print(" - 'location_id' already exists or error:", str(e).split('\n')[0])

    print("\nDatabase updated successfully! You can now run the application.")
