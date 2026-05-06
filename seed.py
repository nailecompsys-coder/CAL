"""
Seed script — run once after first docker compose up.
Creates: admin user, 2 Advent Health locations, 11 surgeons.

Usage:
    docker exec -it cal_api python seed.py
    -- or locally --
    DATABASE_URL=... python seed.py
"""
import os, sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault('SECRET_KEY', 'seed-run-only')
os.environ.setdefault('BASE_URL', 'https://cal.midfloridasurgical.com')
os.environ.setdefault('VAPID_PRIVATE_KEY', 'seed-placeholder')
os.environ.setdefault('VAPID_PUBLIC_KEY', 'seed-placeholder')
os.environ.setdefault('VAPID_EMAIL', 'admin@midfloridasurgical.com')

from app.database import engine, Base, SessionLocal
from app.models import AdminUser, Surgeon, Location
from app.auth import hash_password

def seed():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # ── Admin user ──────────────────────────────────────────────────────
        username = os.getenv('ADMIN_USERNAME', 'admin')
        email    = os.getenv('ADMIN_EMAIL', 'admin@midfloridasurgical.com')
        password = os.getenv('ADMIN_PASSWORD', 'Admin2026!')

        if not db.query(AdminUser).filter_by(username=username).first():
            db.add(AdminUser(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role='admin',
                is_active=True,
            ))
            print(f"  Created admin: {username}")
        else:
            print(f"  Admin '{username}' already exists — skipped")

        # ── Locations ───────────────────────────────────────────────────────
        locations_data = [
            {'name': 'Advent Health Orlando', 'address': '601 E Rollins St', 'city': 'Orlando'},
            {'name': 'Advent Health Lake County', 'address': '600 E Dixie Ave', 'city': 'Clermont'},
        ]
        for loc_d in locations_data:
            if not db.query(Location).filter_by(name=loc_d['name']).first():
                db.add(Location(**loc_d, is_active=True))
                print(f"  Created location: {loc_d['name']}")

        # ── Surgeons ────────────────────────────────────────────────────────
        # 11 surgeons — placeholders, admin will update details as needed
        surgeons_data = [
            {'first_name': 'David',   'last_name': 'Kim',       'specialty': 'Cardiothoracic Surgery', 'color': '#ffffff'},
            {'first_name': 'Sarah',   'last_name': 'Martinez',  'specialty': 'Neurosurgery',           'color': '#ffffff'},
            {'first_name': 'Robert',  'last_name': 'Okafor',    'specialty': 'General Surgery',        'color': '#ffffff'},
            {'first_name': 'Aisha',   'last_name': 'Patel',     'specialty': 'Orthopedics',            'color': '#ffffff'},
            {'first_name': 'James',   'last_name': 'Liu',       'specialty': 'Vascular Surgery',       'color': '#ffffff'},
            {'first_name': 'Aaron',   'last_name': 'Brooks',    'specialty': 'Colorectal Surgery',     'color': '#ffffff'},
            {'first_name': 'Monica',  'last_name': 'Chen',      'specialty': 'Minimally Invasive',     'color': '#ffffff'},
            {'first_name': 'Tyler',   'last_name': 'Washington','specialty': 'Trauma Surgery',         'color': '#ffffff'},
            {'first_name': 'Priya',   'last_name': 'Nair',      'specialty': 'Surgical Oncology',      'color': '#ffffff'},
            {'first_name': 'Carlos',  'last_name': 'Rivera',    'specialty': 'Hepatobiliary Surgery',  'color': '#ffffff'},
            {'first_name': 'Jennifer','last_name': 'Walsh',     'specialty': 'Bariatric Surgery',      'color': '#ffffff'},
        ]

        for s in surgeons_data:
            full = f"{s['first_name']} {s['last_name']}"
            if not db.query(Surgeon).filter_by(first_name=s['first_name'], last_name=s['last_name']).first():
                db.add(Surgeon(**s, is_active=True))
                print(f"  Created surgeon: Dr. {full}")
            else:
                print(f"  Dr. {full} already exists — skipped")

        db.commit()
        print("\nSeed complete.")
        print("Next: generate magic links for each surgeon from the admin portal.")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == '__main__':
    seed()
