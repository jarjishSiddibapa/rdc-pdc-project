# RDC PDC Manager

A role-based web application for managing **post-dated cheques (PDCs)** from the moment a salesperson collects them from a customer to the moment they clear, bounce or are settled another way. It replaces cheque registers kept in spreadsheets with one workflow that has an owner at every step, a full audit trail, dashboards, and Excel reporting.

Built for the finance operations of a multi-location business that runs on Oracle E-Business Suite (R12.2.10). Customers and sales representatives are synchronised from the ERP, so nobody re-types master data.

> **About the screenshots:** they come from a local demo database filled with fictional customers, banks and amounts by [`seed_demo.py`](seed_demo.py). No production data is included in this repository.

![Admin dashboard](docs/screenshots/02-dashboard-admin.png)

## Features

- **Cheque lifecycle workflow.** A strict state machine (13 statuses) with per-role permissions. Each status records who holds the cheque (customer, sales, accounts, bank, credit control or HO accounts).
- **Role-scoped access.** Five roles (Admin, Sales, Accounts, HO Accounts, Credit Control), each with its own dashboard and allowed actions. Admin is view-only on the cheque workflow by design.
- **Cheque journey timeline.** Every transition is stored with the actor, timestamp and remarks, and the next valid steps are shown on the cheque page.
- **Deposits, reconciliation and bounce resolution.** Record bank deposits, mark cheques cleared or bounced with receipt numbers, and resolve bounced cheques by legal notice, NEFT or redeposit. Resolution requires a supporting document.
- **Dashboards with charts.** Status distribution, 12-month trend, top customers by value and location split (Chart.js), filterable by location.
- **Excel report builder.** Filter by status, type, bank, customer, location, salesperson, date ranges and amount range, choose columns and labels, preview, then download a formatted `.xlsx`. Quick exports for the common cases.
- **Oracle ERP sync.** Pulls customers and sales representatives from Oracle R12.2.10 (`python-oracledb`, thick mode) on a schedule configurable from the admin screen (APScheduler), or on demand.
- **Notifications and email.** In-app notifications on status changes, plus SMTP email (configured and tested from the admin screen) for alerts and password resets.
- **Shareable cheque links.** Token-protected public view and QR code so a cheque image can be shown without logging in.
- **Audit logs.** Every create, update and status change is written to an audit table with the old and new values, viewable by admins.
- **Admin tools.** User, bank and location management, merge duplicates, activate or deactivate accounts.

| Cheque list | Cheque journey |
|---|---|
| ![Cheque list](docs/screenshots/04-cheque-list.png) | ![Cheque detail](docs/screenshots/05-cheque-detail.png) |

| HO Accounts dashboard | Sales dashboard |
|---|---|
| ![HO accounts dashboard](docs/screenshots/03-dashboard-ho-accounts.png) | ![Sales dashboard](docs/screenshots/07-dashboard-sales.png) |

| Excel report builder | Audit logs |
|---|---|
| ![Reports](docs/screenshots/06-reports.png) | ![Audit logs](docs/screenshots/08-audit-logs.png) |

## Cheque workflow

```mermaid
stateDiagram-v2
    [*] --> PendingWithCustomer
    PendingWithCustomer --> Collected: Sales collects
    Collected --> Accepted: Accounts accepts
    Collected --> Rejected: Accounts rejects
    Rejected --> Collected: Sales re-collects
    Accepted --> Deposited: Accounts deposits
    Accepted --> Rejected
    Accepted --> NewChequeReceived: Customer replaces cheque
    Accepted --> NEFTReceived: Customer pays by NEFT
    Accepted --> OrderCancelled
    Deposited --> Cleared: Bank clears
    Deposited --> Bounced: Bank returns
    Bounced --> LegalNotice: Legal route
    Bounced --> ClearedViaNEFT: NEFT route
    Bounced --> Redeposited: Redeposit route
    Redeposited --> Deposited
    Redeposited --> Rejected
    NEFTReceived --> ClearedViaNEFT: Credit Control confirms
    Cleared --> [*]
    ClearedViaNEFT --> [*]
    LegalNotice --> [*]
    NewChequeReceived --> [*]
    OrderCancelled --> [*]

    Collected: Collected by Sales Person
    PendingWithCustomer: Pending with Customer
    NewChequeReceived: New Cheque Received
    NEFTReceived: NEFT Received
    OrderCancelled: Order Cancelled
    LegalNotice: Legal Notice Initiated
    ClearedViaNEFT: Cleared via NEFT
```

The transition table and role permissions live in [`app/services/cheque_service.py`](app/services/cheque_service.py). A full flowchart with the status reference table is in [`docs/cheque-lifecycle-flowchart.html`](docs/cheque-lifecycle-flowchart.html) (also as a [PDF](docs/cheque-lifecycle-flowchart.pdf)).

### Roles

| Role | Can do |
|---|---|
| **Sales** | Create cheques and attach the cheque image, mark them collected, report replacement cheques, NEFT receipts and cancelled orders. Sees their own cheques. |
| **Accounts** | Accept or reject collected cheques, record deposits, mark cleared or bounced for their location. |
| **HO Accounts** | Same actions across all locations, plus reconciliation. |
| **Credit Control** | Owns bounced cheques, legal notices and NEFT confirmations. |
| **Admin** | Manage users, banks, locations, email settings, ERP sync and audit logs. Read-only on the workflow. |

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask 3.1, Flask-SQLAlchemy, Flask-Login, Flask-WTF (CSRF), Flask-Migrate, Flask-Session |
| Database | MySQL (application data) |
| ERP integration | Oracle R12.2.10 through `python-oracledb` (thick mode, Oracle Instant Client) |
| Scheduling | APScheduler |
| Reports | openpyxl (formatted Excel export) |
| Frontend | Jinja2 templates, vanilla JavaScript, Chart.js, Tom Select, dark and light themes |
| Production | Gunicorn (config included) or Waitress behind a reverse proxy |

## Project structure

```
app/
  __init__.py        application factory, blueprints, scheduler, health check
  config.py          environment-driven configuration
  decorators.py      role_required / admin_required
  models/            SQLAlchemy models (cheque, customer, user, deposit, audit, ...)
  routes/            blueprints: auth, cheques, dashboard, reports, admin, erp_sync, ...
  services/          cheque workflow, ERP sync, email, notifications, audit, UID generator
  templates/         Jinja2 templates per module
  static/            CSS and JavaScript
docs/                lifecycle flowchart and screenshots
seed_demo.py         fictional demo data generator
gunicorn.conf.py     production server settings
run.py / wsgi.py     development and production entry points
```

## Getting started

**Requirements:** Python 3.10 or newer (developed on 3.14), MySQL 8, and (only for ERP sync) Oracle Instant Client.

```bash
git clone https://github.com/jarjishSiddibapa/rdc-pdc-project.git
cd rdc-pdc-project
python -m venv venv
venv\Scripts\activate            # Windows  (source venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
```

1. Create an empty MySQL database, for example `pdc_manager`.
2. Copy `.env.example` to `.env` and fill in the values (see below).
3. Start the app. Tables and the first admin user are created automatically:

   ```bash
   python run.py
   ```

   Open <http://localhost:50001> and sign in as `admin` with the `ADMIN_SEED_PASSWORD` you set. Change it straight away.

4. *(Optional)* Load demo data to explore the dashboards:

   ```bash
   python seed_demo.py
   ```

   Every demo user (for example `ho.accounts`, `credit.ctrl`, `blr.sales`, `blr.accts`) shares the password defined at the top of `seed_demo.py`. Use it on a throwaway database only.

### Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL, e.g. `mysql+mysqlconnector://user:password@localhost/pdc_manager` (required) |
| `SECRET_KEY` | Flask session secret. Set a long random value in production. |
| `HASHID_SALT` | Salt for the obfuscated IDs in URLs. Set your own value in production. |
| `ADMIN_SEED_PASSWORD` | Password for the first `admin` user, used only when the database is empty |
| `UPLOAD_FOLDER`, `MAX_CONTENT_LENGTH` | Cheque image storage and upload size limit |
| `SESSION_COOKIE_SECURE` | Set to `true` when serving over HTTPS |
| `ERP_DB_HOST`, `ERP_DB_PORT`, `ERP_DB_SERVICE`, `ERP_DB_USERNAME`, `ERP_DB_PASSWORD`, `ERP_INSTANT_CLIENT` | Oracle ERP connection. Leave empty to run without ERP sync. |

SMTP settings for email are stored in the database and edited from **Admin → Email Settings**.

### Production

```bash
gunicorn -c gunicorn.conf.py "app:create_app()"
```

Serve it behind HTTPS and set `SESSION_COOKIE_SECURE=true`. `GET /health` returns a database health check for load balancers.

## Security notes

- CSRF protection on every form, server-side sessions with a 10-minute inactivity timeout, and a client-side warning before logout.
- Passwords stored as hashes (Werkzeug), HTTP-only and SameSite cookies, strict `Content-Security-Policy` and related headers.
- Obfuscated object IDs in URLs (hashids) so database keys are not enumerable.
- Upload extension allow-list and a size limit; role checks enforced on the server for every action.
- Secrets live in `.env`, which is git-ignored. Do not commit it.

## Limitations

- MySQL is required. Some reports use MySQL date functions, so SQLite is not supported.
- There is no automated test suite yet; the workflow rules in `cheque_service.py` are the first candidates for unit tests.
- ERP sync needs network access to the Oracle database and an Oracle Instant Client installation.

## Author

Built by [Jarjish Siddibapa](https://github.com/jarjishSiddibapa) for finance operations at RDC Concrete. See also the [portfolio](https://jarjishsiddibapa.github.io/jarjish-portfolio-website/).
