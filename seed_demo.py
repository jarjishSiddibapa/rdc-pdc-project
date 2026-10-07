"""
Demo data seeder for RDC PDC Manager.

Fills an empty database with fictional locations, users, customers and ~40
cheques spread across the workflow statuses, so the dashboards, reports and
audit views have something to show. All names, banks and amounts are invented.

Usage (from the project root, with DATABASE_URL set):
    python seed_demo.py

Every demo user shares the password defined in DEMO_PASSWORD below.
Never run this against a production database.
"""
import random
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models.bank import Bank
from app.models.cheque import Cheque, ChequeStatusHistory
from app.models.customer import Customer
from app.models.deposit import ChequeDeposit
from app.models.location import Location
from app.models.reconciliation import Reconciliation
from app.models.user import User

DEMO_PASSWORD = 'Demo@1234'
random.seed(7)

PENDING = 'Pending with Customer'
COLLECTED = 'Collected by Sales Person'

# Each cheque walks through these statuses, oldest first.
PATHS = {
    PENDING:                  [PENDING],
    COLLECTED:                [PENDING, COLLECTED],
    'Accepted':               [PENDING, COLLECTED, 'Accepted'],
    'Rejected':               [PENDING, COLLECTED, 'Rejected'],
    'Deposited':              [PENDING, COLLECTED, 'Accepted', 'Deposited'],
    'Cleared':                [PENDING, COLLECTED, 'Accepted', 'Deposited', 'Cleared'],
    'Bounced':                [PENDING, COLLECTED, 'Accepted', 'Deposited', 'Bounced'],
    'Legal Notice Initiated': [PENDING, COLLECTED, 'Accepted', 'Deposited', 'Bounced', 'Legal Notice Initiated'],
    'Cleared via NEFT':       [PENDING, COLLECTED, 'Accepted', 'Deposited', 'Bounced', 'Cleared via NEFT'],
}
# Weighted mix so the charts are not flat.
MIX = ([('Cleared')] * 12 + ['Deposited'] * 6 + ['Accepted'] * 5 + [COLLECTED] * 4 + [PENDING] * 4 +
       ['Bounced'] * 4 + ['Rejected'] * 2 + ['Legal Notice Initiated'] * 2 + ['Cleared via NEFT'] * 2)

LOCATIONS = [('Bangalore', 'N'), ('Mumbai', 'N'), ('Delhi', 'N'), ('Chennai', 'N'), ('Head Office', 'Y')]
BANKS = ['HDFC Bank', 'ICICI Bank', 'State Bank of India', 'Axis Bank', 'Kotak Mahindra Bank']
CUSTOMERS = [
    ('C1001', 'Tech Solutions Pvt Ltd', 'Bangalore'), ('C1002', 'Garuda Enterprises', 'Bangalore'),
    ('C1003', 'Deccan Electronics', 'Bangalore'), ('C2001', 'Reliance Distributors', 'Mumbai'),
    ('C2002', 'Dharavi Textiles', 'Mumbai'), ('C2003', 'Konkan Traders', 'Mumbai'),
    ('C3001', 'Delhi NCR Traders', 'Delhi'), ('C3002', 'Rajdhani Supplies', 'Delhi'),
    ('C4001', 'Chennai Auto Parts', 'Chennai'), ('C4002', 'Marina Exports', 'Chennai'),
]
USERS = [  # username, full name, role, location
    ('ho.accounts', 'Priya Sharma', 'HO_Accounts', 'Head Office'),
    ('credit.ctrl', 'Rahul Nair', 'Credit_Control', 'Head Office'),
    ('blr.sales', 'Arun Kumar', 'Sales', 'Bangalore'), ('blr.accts', 'Suresh Patel', 'Accounts', 'Bangalore'),
    ('mum.sales', 'Nikhil Joshi', 'Sales', 'Mumbai'), ('mum.accts', 'Deepak Shah', 'Accounts', 'Mumbai'),
    ('del.sales', 'Vikram Singh', 'Sales', 'Delhi'), ('del.accts', 'Kavita Gupta', 'Accounts', 'Delhi'),
    ('chn.sales', 'Senthil Kumar', 'Sales', 'Chennai'), ('chn.accts', 'Lakshmi Iyer', 'Accounts', 'Chennai'),
]
LYING_WITH = {
    PENDING: 'Customer', COLLECTED: 'Sales', 'Accepted': 'Accounts', 'Rejected': 'Sales',
    'Deposited': 'Bank', 'Cleared': 'HO Accounts', 'Bounced': 'Credit Control',
    'Legal Notice Initiated': 'Credit Control', 'Cleared via NEFT': 'HO Accounts',
}
CITY_PREFIX = {'Bangalore': 'blr', 'Mumbai': 'mum', 'Delhi': 'del', 'Chennai': 'chn'}


def main():
    app = create_app()
    with app.app_context():
        if Cheque.query.count():
            print('Database already has cheques - refusing to seed twice.')
            return
        now = datetime.utcnow()
        admin = User.query.filter_by(username='admin').first()

        locs = {}
        for name, head in LOCATIONS:
            locs[name] = Location(location_name=name, is_head_office=head)
            db.session.add(locs[name])
        banks = [Bank(bank_name=n) for n in BANKS]
        db.session.add_all(banks)
        db.session.flush()

        users = {}
        for uname, full, role, loc in USERS:
            user = User(username=uname, full_name=full, role=role, email=f'{uname}@example.com',
                        location_id=locs[loc].location_id, avatar_color=random.choice(User.AVATAR_COLORS))
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)
            users[uname] = user
        db.session.flush()

        by_city = {}
        for code, name, city in CUSTOMERS:
            cust = Customer(customer_code=code, customer_name=name, city=city, contact_person='Demo Contact',
                            contact_phone='9000000000', contact_email=f'{code.lower()}@example.com',
                            created_by=admin.user_id)
            db.session.add(cust)
            by_city.setdefault(city, []).append(cust)
        db.session.flush()

        for i, status in enumerate(MIX, start=1):
            city = random.choice(list(by_city))
            cust = random.choice(by_city[city])
            sales, accts = users[f'{CITY_PREFIX[city]}.sales'], users[f'{CITY_PREFIX[city]}.accts']
            ho, cc = users['ho.accounts'], users['credit.ctrl']
            start_days = random.randint(12, 150)
            bank = random.choice(banks)
            cheque = Cheque(
                uid=f'PDC-{now:%Y%m%d}-{i:04d}', customer_id=cust.customer_id,
                cheque_number=str(100000 + random.randint(0, 899999)),
                cheque_date=(now - timedelta(days=start_days - random.randint(0, 10))).date(),
                bank_id=bank.bank_id, bank_name=bank.bank_name,
                amount=random.choice([25000, 48000, 75000, 120000, 180000, 250000, 400000]),
                cheque_type=random.choice(['PDC', 'PDC', 'PDC', 'Open']), status=status,
                lying_with=LYING_WITH[status], salesperson_id=sales.user_id,
                location_id=locs[city].location_id, created_by=sales.user_id,
                created_at=now - timedelta(days=start_days),
            )
            db.session.add(cheque)
            db.session.flush()

            path = PATHS[status]
            step = max(start_days // (len(path) + 1), 1)
            actors = {PENDING: sales, COLLECTED: sales, 'Accepted': accts, 'Rejected': accts,
                      'Deposited': accts, 'Cleared': ho, 'Bounced': ho,
                      'Legal Notice Initiated': cc, 'Cleared via NEFT': cc}
            previous = None
            for n, step_status in enumerate(path):
                db.session.add(ChequeStatusHistory(
                    cheque_id=cheque.cheque_id, old_status=previous, new_status=step_status,
                    updated_by=actors[step_status].user_id,
                    updated_at=now - timedelta(days=start_days - step * n), remarks='Demo data'))
                previous = step_status
            if 'Deposited' in path:
                db.session.add(ChequeDeposit(
                    cheque_id=cheque.cheque_id, deposit_number=f'DEP-{i:04d}',
                    deposit_date=(now - timedelta(days=max(start_days - step * 3, 1))).date(),
                    deposit_bank=bank.bank_name, deposit_branch='Main Branch', created_by=accts.user_id))
            if status in ('Cleared', 'Bounced'):
                db.session.add(Reconciliation(
                    cheque_id=cheque.cheque_id, is_cleared='Y' if status == 'Cleared' else 'N',
                    cleared_date=(now - timedelta(days=max(step, 1))).date(),
                    receipt_number=f'REC-{i:04d}', uploaded_by=ho.user_id))
        db.session.commit()
        print(f'Seeded {Cheque.query.count()} cheques and {User.query.count()} users.')


if __name__ == '__main__':
    main()
