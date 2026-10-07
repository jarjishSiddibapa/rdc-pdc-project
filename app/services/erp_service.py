"""
Oracle ERP R12.2.10 — Customer & Salesrep Sync Service

Connection: python-oracledb thick mode (Oracle Instant Client).
Mirrors the connection approach used in the GL-extractor script:
  - oracledb.init_oracle_client() called once at module level
  - oracledb.connect(user, password, dsn) per sync run
  - cursor.arraysize for efficient bulk row fetching

Configure in .env:
    ERP_DB_HOST, ERP_DB_PORT, ERP_DB_SERVICE,
    ERP_DB_USERNAME, ERP_DB_PASSWORD,
    ERP_INSTANT_CLIENT  (path to Oracle Instant Client directory)

Sync behaviour (in order):
  1. Salesreps  → created as INACTIVE Sales users; admin activates + assigns location manually.
  2. Customers  → created/updated matched on ACCOUNT_NUMBER (erp_customer_id)
                  Customer's effective location = their salesperson's location.

Locations are managed manually by admin — not synced from ERP.
"""
import re
import secrets
import logging
from app.utils import now_ist

log = logging.getLogger(__name__)

# ── One-time thick-mode initialisation (module level, like the GL extractor) ──
# Must run before any connection is opened.  Repeated calls are silently ignored.
_oracle_client_initialised = False

def _init_oracle_client(lib_dir: str) -> None:
    global _oracle_client_initialised
    if _oracle_client_initialised:
        return
    try:
        import oracledb
        oracledb.init_oracle_client(lib_dir=lib_dir)
        _oracle_client_initialised = True
        log.info("Oracle thick mode initialised from %s", lib_dir)
    except Exception as exc:
        # Already initialised in this process, or path note — oracledb logs this.
        log.debug("Oracle client init note: %s", exc)


from flask import current_app
from app.extensions import db
from app.models.customer import Customer
from app.models.user import User


class ERPConnectionError(Exception):
    pass


# ── Oracle ERP Queries ───────────────────────────────────────────────────────

# Fetches all active Bill-To customers with their linked salesrep and city.
#
# IMPORTANT — why no GST/PAN correlated subqueries:
#   The original query had two correlated subqueries against JAI_PARTY_REGS /
#   JAI_PARTY_REG_LINES (one for GST, one for PAN).  Each fires once per result
#   row.  SQL Developer shows "2 s" because it only fetches the first 50 rows.
#   When Python fetches ALL rows (fetchmany loop), those subqueries fire thousands
#   of times → 12+ minute syncs.  GST/PAN are managed manually in the admin UI.
#
# TBL2 JOIN note:
#   TBL2 is a SHIP_TO address subquery joined on PARTY_ID.  One party can have
#   multiple SHIP_TO sites, but SELECT DISTINCT on the outer query deduplicates
#   them (CITY/STATE are the only TBL2 columns projected, and we only need one).
CUSTOMER_SYNC_QUERY = """
SELECT DISTINCT
    CUST.ACCOUNT_NUMBER                     CUSTOMER_NUMBER,
    PARTY.PARTY_NAME                        CUST_NAME,
    PARTY.PRIMARY_PHONE_NUMBER              PHONE_NUMBER,
    CUST.GLOBAL_ATTRIBUTE1                  EMAIL_ADDRESS,
    CUST.ATTRIBUTE10                        SALESPERSON,
    SR.SALESREP_ID,
    SR.NAME                                 SALESREP_NAME,
    SR.SALESREP_NUMBER,
    TBL2.CITY,
    TBL2.STATE
FROM
    apps.HZ_CUST_ACCOUNTS_ALL       CUST,
    apps.HZ_CUST_ACCT_SITES_ALL     ACCT,
    apps.HZ_CUST_SITE_USES_ALL      SHIP,
    apps.HZ_PARTY_SITES             PARTY_SITE,
    apps.HZ_LOCATIONS               LOC,
    apps.HZ_PARTIES                 PARTY,
    apps.jtf_rs_salesreps           SR,
    (SELECT HP_SHIP.PARTY_ID,
            HL_SHIP.CITY,
            HL_SHIP.STATE
       FROM apps.HZ_CUST_ACCT_SITES_ALL  HCSA_SHIP,
            apps.HZ_PARTY_SITES          HPS_SHIP,
            apps.HZ_CUST_SITE_USES_ALL   HCSUA_SHIP,
            apps.HZ_CUST_ACCOUNTS_ALL    HCA_SHIP,
            apps.HZ_PARTIES              HP_SHIP,
            apps.HZ_LOCATIONS            HL_SHIP
      WHERE HPS_SHIP.PARTY_SITE_ID       = HCSA_SHIP.PARTY_SITE_ID
        AND HCSA_SHIP.CUST_ACCT_SITE_ID  = HCSUA_SHIP.CUST_ACCT_SITE_ID
        AND HCA_SHIP.CUST_ACCOUNT_ID     = HCSA_SHIP.CUST_ACCOUNT_ID
        AND HP_SHIP.PARTY_ID             = HCA_SHIP.PARTY_ID
        AND HL_SHIP.LOCATION_ID          = HPS_SHIP.LOCATION_ID
        AND HCSUA_SHIP.SITE_USE_CODE     = 'SHIP_TO'
        AND HCA_SHIP.STATUS              = 'A') TBL2
WHERE
    CUST.CUST_ACCOUNT_ID        = ACCT.CUST_ACCOUNT_ID
    AND ACCT.CUST_ACCT_SITE_ID  = SHIP.CUST_ACCT_SITE_ID
    AND ACCT.ORG_ID             = SHIP.ORG_ID
    AND SHIP.SITE_USE_CODE      = 'BILL_TO'
    AND CUST.STATUS             = 'A'
    AND LOC.LOCATION_ID         = PARTY_SITE.LOCATION_ID
    AND ACCT.PARTY_SITE_ID      = PARTY_SITE.PARTY_SITE_ID
    AND CUST.PARTY_ID           = PARTY.PARTY_ID
    AND TBL2.PARTY_ID           = PARTY.PARTY_ID
    AND SR.NAME                 = CUST.ATTRIBUTE10
    AND CUST.ATTRIBUTE10        IS NOT NULL
"""
# ─────────────────────────────────────────────────────────────────────────────


def _get_erp_config():
    return {
        'host':           current_app.config.get('ERP_DB_HOST', '').strip(),
        'port':           current_app.config.get('ERP_DB_PORT', '1528').strip(),
        'service':        current_app.config.get('ERP_DB_SERVICE', '').strip(),
        'username':       current_app.config.get('ERP_DB_USERNAME', '').strip(),
        'password':       current_app.config.get('ERP_DB_PASSWORD', '').strip(),
        'instant_client': current_app.config.get('ERP_INSTANT_CLIENT',
                                                  r'C:\oracle\instantclient').strip(),
    }


def is_configured():
    cfg = _get_erp_config()
    return bool(cfg['host'] and cfg['service'] and cfg['username'])


def _get_connection():
    """
    Open an oracledb connection using thick mode (Oracle Instant Client).
    Same approach as the GL-extractor script.
    Raises ERPConnectionError on failure.
    """
    try:
        import oracledb
    except ImportError:
        raise ERPConnectionError(
            "oracledb is not installed. Run: pip install oracledb"
        )

    cfg = _get_erp_config()
    if not cfg['host']:
        raise ERPConnectionError(
            "ERP_DB_HOST is not configured. Set it in .env to enable sync."
        )

    _init_oracle_client(cfg['instant_client'])

    dsn = f"{cfg['host']}:{cfg['port']}/{cfg['service']}"
    try:
        conn = oracledb.connect(
            user=cfg['username'],
            password=cfg['password'],
            dsn=dsn,
        )
        log.info("Connected to Oracle ERP at %s", dsn)
        return conn
    except oracledb.DatabaseError as e:
        raise ERPConnectionError(f"Cannot connect to Oracle ERP ({dsn}): {e}")


def fetch_all_from_erp(cb=None):
    """
    Execute the customer sync query against Oracle ERP.
    Returns a list of dicts with lowercase column names.
    cursor.arraysize=500 fetches 500 rows per network round-trip (like the GL extractor).
    cb: optional progress callback(type, msg) — called every 500 rows during fetch
        so the UI shows activity even while Oracle is still sending data.
    """
    _cb = cb or (lambda t, m: None)
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.arraysize = 500          # bulk fetch — reduces round-trips
        _cb('info', 'Connected. Executing ERP query…')
        cursor.execute(CUSTOMER_SYNC_QUERY)
        cols = [col[0].lower() for col in cursor.description]
        rows = []
        while True:
            batch = cursor.fetchmany()  # honours arraysize
            if not batch:
                break
            rows.extend(dict(zip(cols, row)) for row in batch)
            # Heartbeat every 500 rows so the log panel shows progress during fetch
            if len(rows) % 500 == 0:
                _cb('info', f'Fetching from Oracle ERP… {len(rows):,} rows received so far')
        log.info("Oracle ERP query returned %d rows", len(rows))
        _cb('info', f'Fetch complete — {len(rows):,} total rows received from ERP.')
        return rows
    finally:
        conn.close()


# ── Username generation ───────────────────────────────────────────────────────

def _make_username(full_name: str) -> str:
    """'Rahul Nair' → 'rahul.nair', guaranteed unique in DB."""
    sanitised = re.sub(r'[^a-zA-Z0-9 ]', '', full_name).strip().lower()
    parts = sanitised.split()
    base = f"{parts[0]}.{parts[-1]}" if len(parts) >= 2 else (parts[0] if parts else 'salesrep')
    username = base
    suffix = 2
    while User.query.filter_by(username=username).first():
        username = f"{base}.{suffix}"
        suffix += 1
    return username


# ── Main sync function ────────────────────────────────────────────────────────

def sync_from_erp(created_by=None, progress_cb=None):
    """
    Full sync from Oracle ERP — salesreps then customers.
      1. Salesrep sync  — create/update Sales users; admin assigns locations manually.
      2. Customer sync  — upsert Customers, linked to their salesrep.

    progress_cb: optional callable(type, msg) where type is 'info'|'success'|'warn'|'error'.
    Locations are NOT synced from ERP — managed manually by admin.
    """
    cb = progress_cb or (lambda t, m: None)

    cb('info', '━━━ Step 1 / 2 — Syncing salesreps & customers from ERP ━━━')
    cb('info', 'Connecting to Oracle ERP…')
    rows = fetch_all_from_erp(cb=cb)
    cb('info', f'Starting upsert of {len(rows):,} rows…')
    return _upsert_from_rows(rows, created_by=created_by, progress_cb=cb)


def _upsert_from_rows(rows, created_by=None, progress_cb=None):
    """
    Upsert salesreps and customers from ERP rows.

    Location assignment:
      - Salesrep locations are NOT auto-assigned here — admin does it manually
        in User Management after the sync.
      - Customer location is derived from their salesperson (no direct link stored).
    """
    cb = progress_cb or (lambda t, m: None)
    cust_created = cust_updated = user_created = user_updated = 0
    errors = []

    # ── Compute totals upfront so the UI can show % progress ─────────────────
    users_total = len({row.get('salesrep_id') for row in rows if row.get('salesrep_id')})
    cust_total  = len({str(row.get('customer_number') or '').strip()
                       for row in rows if row.get('customer_number')})
    cb('progress', {'users_total': users_total, 'customers_total': cust_total,
                    'users_done': 0, 'customers_done': 0})
    cb('info', f'Found {users_total} unique salesreps and {cust_total} unique customers to process.')

    # ── Pre-load existing records into memory (eliminates N+1 DB queries) ────
    existing_users_by_salesrep_id     = {
        u.salesrep_id: u
        for u in User.query.filter(User.salesrep_id.isnot(None)).all()
    }
    existing_users_by_sales_person_id = {
        u.sales_person_id: u
        for u in User.query.filter(User.sales_person_id.isnot(None)).all()
    }
    # Fallback: manually-created Sales users matched by full name (case-insensitive).
    existing_sales_users_by_name = {
        u.full_name.strip().lower(): u
        for u in User.query.filter_by(role='Sales').all()
    }
    existing_custs_by_erp_id = {
        c.erp_customer_id: c
        for c in Customer.query.filter(Customer.erp_customer_id.isnot(None)).all()
    }
    existing_custs_by_code = {c.customer_code: c for c in Customer.query.all()}

    # ── 1. Salesreps ─────────────────────────────────────────────────────────
    seen_sr = {}   # salesrep_id (int) → User instance
    for row in rows:
        erp_sr_id = row.get('salesrep_id')
        sr_number = str(row.get('salesrep_number') or '').strip()
        sr_name   = str(row.get('salesrep_name') or '').strip()
        if not erp_sr_id or not sr_name:
            continue
        if erp_sr_id in seen_sr:
            continue   # already processed

        try:
            # Match priority:
            #   1. By ERP salesrep_id            — previous ERP sync
            #   2. By ERP salesrep_number string  — manually set ERP ID on user
            #   3. By full name (Sales role)       — manually created user, no ERP IDs yet
            user = (
                existing_users_by_salesrep_id.get(erp_sr_id)
                or (existing_users_by_sales_person_id.get(sr_number) if sr_number else None)
                or existing_sales_users_by_name.get(sr_name.lower())
            )

            if user:
                user.salesrep_id     = erp_sr_id
                user.sales_person_id = sr_number or user.sales_person_id
                user.updated_at      = now_ist()
                user_updated += 1
                existing_users_by_salesrep_id[erp_sr_id] = user
                status_tag = '(active)' if user._is_active == 'Y' else '(inactive — needs activation)'
                cb('info', f'Salesrep matched: {sr_name} → user "{user.username}" {status_tag}')
            else:
                username = _make_username(sr_name)
                user = User(
                    username        = username,
                    full_name       = sr_name,
                    role            = 'Sales',
                    salesrep_id     = erp_sr_id,
                    sales_person_id = sr_number or None,
                    avatar_color    = User.generate_avatar_color(),
                    _is_active      = 'N',
                    created_by      = created_by,
                    created_at      = now_ist(),
                )
                user.password_hash = secrets.token_hex(60)  # unusable until admin resets
                db.session.add(user)
                user_created += 1
                existing_users_by_salesrep_id[erp_sr_id] = user
                existing_sales_users_by_name[sr_name.lower()] = user
                cb('success',
                   f'New salesrep: {sr_name} (username: {username}) — '
                   f'inactive, needs activation + location assignment')

            seen_sr[erp_sr_id] = user
            cb('progress', {'users_done': len(seen_sr)})

        except Exception as e:
            errors.append(f"Salesrep '{sr_name}' (ID {erp_sr_id}): {e}")
            cb('error', f'Error on salesrep {sr_name}: {e}')
            cb('progress', {'users_done': len(seen_sr)})

    db.session.flush()   # assign PKs before customer FK references

    # ── 2. Customers ─────────────────────────────────────────────────────────
    # Customer location is derived from their salesperson's location —
    # no direct customer→location link is stored here.
    seen_cust = set()
    for row in rows:
        cust_number = str(row.get('customer_number') or '').strip()
        if not cust_number or cust_number in seen_cust:
            continue
        seen_cust.add(cust_number)

        try:
            cust_name  = str(row.get('cust_name') or cust_number).strip()
            phone      = str(row.get('phone_number') or '').strip() or None
            email      = str(row.get('email_address') or '').strip() or None
            city       = str(row.get('city') or '').strip() or None

            erp_sr_id  = row.get('salesrep_id')
            sp_user    = seen_sr.get(erp_sr_id)
            sp_user_id = sp_user.user_id if sp_user else None

            customer = (existing_custs_by_erp_id.get(cust_number)
                        or existing_custs_by_code.get(cust_number))

            # ── Fallback DB check ─────────────────────────────────────────────
            # The in-memory dicts can miss an existing customer when:
            #   • A previous partial sync committed some rows then failed
            #   • The customer was created manually with erp_customer_id=NULL
            #   • SQLAlchemy's identity map has stale state after flush()
            # Re-querying before INSERT costs one SELECT but prevents an
            # IntegrityError on customer_code that would roll back the entire
            # batch and crash the scheduler job.
            if not customer:
                customer = Customer.query.filter(
                    db.or_(
                        Customer.erp_customer_id == cust_number,
                        Customer.customer_code   == cust_number,
                    )
                ).first()
                if customer:
                    # Back-fill the in-memory caches so subsequent lookups are fast
                    existing_custs_by_erp_id[cust_number] = customer
                    existing_custs_by_code[cust_number]   = customer
                    log.debug('Customer %s found via fallback DB query (missed by pre-load)', cust_number)

            if customer:
                customer.customer_name   = cust_name
                customer.contact_phone   = phone or customer.contact_phone
                customer.contact_email   = email or customer.contact_email
                customer.city            = city  or customer.city
                customer.erp_customer_id = cust_number
                if sp_user_id:
                    customer.salesperson_id = sp_user_id
                customer.updated_at      = now_ist()
                cust_updated += 1
                existing_custs_by_erp_id[cust_number] = customer
            else:
                customer = Customer(
                    customer_code    = cust_number,
                    customer_name    = cust_name,
                    contact_phone    = phone,
                    contact_email    = email,
                    city             = city,
                    erp_customer_id  = cust_number,
                    salesperson_id   = sp_user_id,
                    is_active        = 'Y',
                    created_by       = created_by,
                    created_at       = now_ist(),
                )
                db.session.add(customer)
                cust_created += 1
                existing_custs_by_erp_id[cust_number] = customer
                existing_custs_by_code[cust_number]   = customer
                cb('success', f'New customer: {cust_name} ({cust_number})'
                              + (f' — {city}' if city else ''))

            cust_done = cust_created + cust_updated
            cb('progress', {'customers_done': cust_done})
            if cust_done > 0 and cust_done % 50 == 0:
                cb('info', f'… {cust_done} customers processed '
                           f'({cust_created} new, {cust_updated} updated)')

        except Exception as e:
            errors.append(f"Customer '{cust_number}': {e}")
            cb('error', f'Error on customer {cust_number}: {e}')
            cb('progress', {'customers_done': cust_created + cust_updated})

    # ── Commit with rollback guard ────────────────────────────────────────────
    # Wrapping the commit prevents the session from being left in a "rollback
    # pending" state if any queued INSERT violates a unique constraint that
    # somehow slipped past the pre-load dicts and the fallback query above.
    try:
        db.session.commit()
    except Exception as commit_err:
        db.session.rollback()
        errors.append(f'Commit failed: {commit_err}')
        cb('error', f'Commit failed — changes rolled back. Error: {commit_err}')
        log.exception('[ERP Sync] Commit failed during customer upsert')

    cb('info', '─' * 40)
    cb('success' if not errors else 'warn',
       f'Salesrep + customer sync complete — '
       f'{cust_created} customers created, {cust_updated} updated | '
       f'{user_created} salesreps created, {user_updated} matched'
       + (f' | {len(errors)} error(s)' if errors else ''))

    return {
        'cust_created': cust_created,
        'cust_updated': cust_updated,
        'user_created': user_created,
        'user_updated': user_updated,
        'errors':       errors,
    }
