"""
Indian PET Plastic Credit Framework
Flask Backend — app.py

Run:  python3 app.py
Then open:  http://127.0.0.1:8080
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, random, string
from datetime import datetime, timedelta
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = 'pet-credit-secret-key-change-in-production'

DB = 'database.db'

# ──────────────────────────────────────────────
# DATABASE SETUP
# ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS companies (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name  TEXT NOT NULL,
        email         TEXT NOT NULL UNIQUE,
        password      TEXT NOT NULL,
        is_verified   INTEGER DEFAULT 0,
        is_admin      INTEGER DEFAULT 0,
        created_at    TEXT DEFAULT (datetime('now'))
    )''')
    try:
        c.execute('ALTER TABLE companies ADD COLUMN is_admin INTEGER DEFAULT 0')
    except:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS pcc_entries (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id   INTEGER NOT NULL,
        month_idx    INTEGER NOT NULL,
        date_str     TEXT,
        category     TEXT,
        weight       REAL,
        esg          REAL,
        loc_f        REAL,
        eco_e        REAL,
        esg_g        REAL,
        pcc          REAL,
        created_at   TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (company_id) REFERENCES companies(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS ppc_entries (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id   INTEGER NOT NULL,
        month_idx    INTEGER NOT NULL,
        date_str     TEXT,
        product      TEXT,
        weight       REAL,
        esg          REAL,
        service_life REAL,
        exposure_p   REAL,
        proc_w       REAL,
        esg_g        REAL,
        ppc          REAL,
        created_at   TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (company_id) REFERENCES companies(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS access_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id    INTEGER,
        company_name  TEXT,
        email         TEXT,
        action        TEXT,
        timestamp     TEXT DEFAULT (datetime('now')),
        ip_address    TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS otp_store (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        email       TEXT NOT NULL,
        otp         TEXT NOT NULL,
        purpose     TEXT NOT NULL,
        expires_at  TEXT NOT NULL,
        used        INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )''')

    # Default email settings
    defaults = [
        ('smtp_email',    'gandhijidaksh@gmail.com'),
        ('smtp_password', ''),
        ('smtp_host',     'smtp.gmail.com'),
        ('smtp_port',     '587'),
    ]
    for key, val in defaults:
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)', (key, val))

    # Default admin account
    existing = c.execute("SELECT id FROM companies WHERE email='gandhijidaksh@gmail.com'").fetchone()
    if not existing:
        c.execute('''INSERT INTO companies (company_name, email, password, is_verified, is_admin)
                     VALUES (?, ?, ?, 1, 1)''',
                  ('IIT Delhi Admin', 'gandhijidaksh@gmail.com',
                   generate_password_hash('admin123')))
    else:
        # Always ensure superadmin has is_admin=1
        c.execute("UPDATE companies SET is_admin=1 WHERE email='gandhijidaksh@gmail.com'")

    conn.commit()
    conn.close()

# ──────────────────────────────────────────────
# EMAIL HELPERS
# ──────────────────────────────────────────────
def get_setting(key):
    conn = get_db()
    row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else ''

def send_email(to_email, subject, html_body):
    smtp_email    = get_setting('smtp_email')
    smtp_password = get_setting('smtp_password')
    smtp_host     = get_setting('smtp_host')
    smtp_port     = int(get_setting('smtp_port') or 587)

    if not smtp_password:
        print(f'[EMAIL] No SMTP password set. Would send to {to_email}: {subject}')
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = smtp_email
        msg['To']      = to_email
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f'[EMAIL ERROR] {e}')
        return False

def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))

def create_otp(email, purpose):
    otp = generate_otp()
    expires_at = (datetime.now() + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    # Invalidate old OTPs for same email+purpose
    conn.execute('UPDATE otp_store SET used=1 WHERE email=? AND purpose=?', (email, purpose))
    conn.execute('INSERT INTO otp_store (email, otp, purpose, expires_at) VALUES (?,?,?,?)',
                 (email, otp, purpose, expires_at))
    conn.commit()
    conn.close()
    return otp

def verify_otp(email, otp, purpose):
    conn = get_db()
    row = conn.execute('''SELECT * FROM otp_store
        WHERE email=? AND otp=? AND purpose=? AND used=0
        AND expires_at > datetime('now')
        ORDER BY id DESC LIMIT 1''', (email, otp, purpose)).fetchone()
    if row:
        conn.execute('UPDATE otp_store SET used=1 WHERE id=?', (row['id'],))
        conn.commit()
    conn.close()
    return row is not None

def generate_reset_token():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))

# ──────────────────────────────────────────────
# AUTH HELPERS
# ──────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'company_id' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def log_action(company_id, company_name, email, action):
    conn = get_db()
    conn.execute('''INSERT INTO access_log (company_id, company_name, email, action, ip_address)
                    VALUES (?, ?, ?, ?, ?)''',
                 (company_id, company_name, email, action,
                  request.remote_addr or 'unknown'))
    conn.commit()
    conn.close()

# ──────────────────────────────────────────────
# PAGES
# ──────────────────────────────────────────────
@app.route('/')
def index():
    if 'company_id' in session:
        if session.get('email') == 'gandhijidaksh@gmail.com':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    if 'company_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    return render_template('dashboard.html',
                           company_name=session.get('company_name'),
                           email=session.get('email'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('admin.html')

# ──────────────────────────────────────────────
# AUTH API — REGISTER
# ──────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    data         = request.get_json()
    company_name = data.get('company_name', '').strip()
    email        = data.get('email', '').strip().lower()
    password     = data.get('password', '')

    if not company_name or not email or not password:
        return jsonify({'ok': False, 'error': 'All fields are required.'})
    if len(password) < 6:
        return jsonify({'ok': False, 'error': 'Password must be at least 6 characters.'})

    conn = get_db()
    existing = conn.execute('SELECT id FROM companies WHERE email=?', (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'ok': False, 'error': 'An account with this email already exists.'})

    conn.execute('INSERT INTO companies (company_name, email, password, is_verified) VALUES (?,?,?,0)',
                 (company_name, email, generate_password_hash(password)))
    conn.commit()
    conn.close()

    # Send OTP for email verification
    otp = create_otp(email, 'verify')
    send_email(email, 'Verify your PET Credit Portal account',
        f'''<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;background:#0d1117;color:#e6edf3;border-radius:12px;">
        <h2 style="color:#1a9e8f;">♻️ PET Plastic Credit Portal</h2>
        <p style="margin-top:16px;">Your verification OTP is:</p>
        <div style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#1a9e8f;margin:20px 0;">{otp}</div>
        <p style="color:#8b949e;font-size:13px;">This OTP expires in 10 minutes. Do not share it.</p>
        </div>''')

    return jsonify({'ok': True, 'step': 'verify', 'email': email,
                    'message': f'OTP sent to {email}. Please verify your account.'})

# ──────────────────────────────────────────────
# AUTH API — VERIFY OTP (registration)
# ──────────────────────────────────────────────
@app.route('/api/verify-registration', methods=['POST'])
def verify_registration():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()
    otp   = data.get('otp', '').strip()

    if not verify_otp(email, otp, 'verify'):
        return jsonify({'ok': False, 'error': 'Invalid or expired OTP. Please try again.'})

    conn = get_db()
    conn.execute('UPDATE companies SET is_verified=1 WHERE email=?', (email,))
    conn.commit()
    company = conn.execute('SELECT * FROM companies WHERE email=?', (email,)).fetchone()
    conn.close()

    session['company_id']   = company['id']
    session['company_name'] = company['company_name']
    session['email']        = email
    session['is_admin']     = bool(company['is_admin'])
    log_action(company['id'], company['company_name'], email, 'registered')
    return jsonify({'ok': True, 'redirect': url_for('dashboard')})

# ──────────────────────────────────────────────
# AUTH API — LOGIN (step 1: password check)
# ──────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data     = request.get_json()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    conn    = get_db()
    company = conn.execute('SELECT * FROM companies WHERE email=?', (email,)).fetchone()
    conn.close()

    if not company or not check_password_hash(company['password'], password):
        return jsonify({'ok': False, 'error': 'Invalid email or password.'})

    # Admin bypasses OTP
    if company['is_admin']:
        session['company_id']   = company['id']
        session['company_name'] = company['company_name']
        session['email']        = email
        session['is_admin']     = True
        log_action(company['id'], company['company_name'], email, 'logged_in')
        return jsonify({'ok': True, 'redirect': url_for('admin_dashboard')})

    # Send login OTP
    otp = create_otp(email, 'login')
    sent = send_email(email, 'Your PET Credit Portal login OTP',
        f'''<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;background:#0d1117;color:#e6edf3;border-radius:12px;">
        <h2 style="color:#1a9e8f;">♻️ PET Plastic Credit Portal</h2>
        <p style="margin-top:16px;">Your login OTP is:</p>
        <div style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#1a9e8f;margin:20px 0;">{otp}</div>
        <p style="color:#8b949e;font-size:13px;">This OTP expires in 10 minutes. Do not share it with anyone.</p>
        <p style="color:#8b949e;font-size:13px;">If you did not request this, please ignore this email.</p>
        </div>''')

    if not sent:
        # If email not configured, log OTP to console for testing
        print(f'[OTP for {email}]: {otp}')

    return jsonify({'ok': True, 'step': 'otp', 'email': email,
                    'message': f'OTP sent to {email}. Valid for 10 minutes.'})

# ──────────────────────────────────────────────
# AUTH API — LOGIN (step 2: OTP verify)
# ──────────────────────────────────────────────
@app.route('/api/verify-login-otp', methods=['POST'])
def verify_login_otp():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()
    otp   = data.get('otp', '').strip()

    if not verify_otp(email, otp, 'login'):
        return jsonify({'ok': False, 'error': 'Invalid or expired OTP. Please try again.'})

    conn    = get_db()
    company = conn.execute('SELECT * FROM companies WHERE email=?', (email,)).fetchone()
    conn.close()

    if not company:
        return jsonify({'ok': False, 'error': 'Account not found.'})

    session['company_id']   = company['id']
    session['company_name'] = company['company_name']
    session['email']        = email
    session['is_admin']     = bool(company['is_admin'])
    log_action(company['id'], company['company_name'], email, 'logged_in')
    redirect_url = url_for('admin_dashboard') if company['is_admin'] else url_for('dashboard')
    return jsonify({'ok': True, 'redirect': redirect_url})

# ──────────────────────────────────────────────
# AUTH API — FORGOT PASSWORD
# ──────────────────────────────────────────────
@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()

    conn    = get_db()
    company = conn.execute('SELECT * FROM companies WHERE email=?', (email,)).fetchone()
    conn.close()

    # Always return success to prevent email enumeration
    if company:
        otp = create_otp(email, 'reset')
        send_email(email, 'Reset your PET Credit Portal password',
            f'''<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;background:#0d1117;color:#e6edf3;border-radius:12px;">
            <h2 style="color:#1a9e8f;">♻️ PET Plastic Credit Portal</h2>
            <p style="margin-top:16px;">Your password reset OTP is:</p>
            <div style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#1a9e8f;margin:20px 0;">{otp}</div>
            <p style="color:#8b949e;font-size:13px;">This OTP expires in 10 minutes.</p>
            <p style="color:#8b949e;font-size:13px;">If you did not request a password reset, please ignore this email.</p>
            </div>''')
        print(f'[RESET OTP for {email}]: {otp}')

    return jsonify({'ok': True, 'message': f'If {email} is registered, a reset OTP has been sent.'})

# ──────────────────────────────────────────────
# AUTH API — RESET PASSWORD
# ──────────────────────────────────────────────
@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data         = request.get_json()
    email        = data.get('email', '').strip().lower()
    otp          = data.get('otp', '').strip()
    new_password = data.get('new_password', '')

    if len(new_password) < 6:
        return jsonify({'ok': False, 'error': 'Password must be at least 6 characters.'})

    if not verify_otp(email, otp, 'reset'):
        return jsonify({'ok': False, 'error': 'Invalid or expired OTP.'})

    conn = get_db()
    conn.execute('UPDATE companies SET password=? WHERE email=?',
                 (generate_password_hash(new_password), email))
    conn.commit()
    conn.close()

    log_action(None, None, email, 'password_reset')
    return jsonify({'ok': True, 'message': 'Password reset successfully. Please log in.'})

# ──────────────────────────────────────────────
# AUTH API — LOGOUT
# ──────────────────────────────────────────────
@app.route('/api/logout', methods=['POST'])
def logout():
    if 'company_id' in session:
        log_action(session['company_id'], session.get('company_name'),
                   session.get('email'), 'logged_out')
    session.clear()
    return jsonify({'ok': True, 'redirect': url_for('login_page')})

# ──────────────────────────────────────────────
# PCC ENTRIES API
# ──────────────────────────────────────────────
@app.route('/api/pcc', methods=['GET'])
@login_required
def get_pcc():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM pcc_entries WHERE company_id=? ORDER BY month_idx, id',
        (session['company_id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/pcc', methods=['POST'])
@login_required
def add_pcc():
    d = request.get_json()
    conn = get_db()
    cur = conn.execute('''INSERT INTO pcc_entries
        (company_id, month_idx, date_str, category, weight, esg, loc_f, eco_e, esg_g, pcc)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (session['company_id'], d['month_idx'], d['date_str'], d['category'],
         d['weight'], d['esg'], d['loc_f'], d['eco_e'], d['esg_g'], d['pcc']))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return jsonify({'ok': True, 'id': new_id})

@app.route('/api/pcc/<int:entry_id>', methods=['PUT'])
@login_required
def update_pcc(entry_id):
    d = request.get_json()
    conn = get_db()
    conn.execute('''UPDATE pcc_entries SET
        date_str=?, category=?, weight=?, esg=?, loc_f=?, eco_e=?, esg_g=?, pcc=?
        WHERE id=? AND company_id=?''',
        (d['date_str'], d['category'], d['weight'], d['esg'],
         d['loc_f'], d['eco_e'], d['esg_g'], d['pcc'],
         entry_id, session['company_id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/pcc/<int:entry_id>', methods=['DELETE'])
@login_required
def delete_pcc(entry_id):
    conn = get_db()
    conn.execute('DELETE FROM pcc_entries WHERE id=? AND company_id=?',
                 (entry_id, session['company_id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ──────────────────────────────────────────────
# PPC ENTRIES API
# ──────────────────────────────────────────────
@app.route('/api/ppc', methods=['GET'])
@login_required
def get_ppc():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM ppc_entries WHERE company_id=? ORDER BY month_idx, id',
        (session['company_id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/ppc', methods=['POST'])
@login_required
def add_ppc():
    d = request.get_json()
    conn = get_db()
    cur = conn.execute('''INSERT INTO ppc_entries
        (company_id, month_idx, date_str, product, weight, esg,
         service_life, exposure_p, proc_w, esg_g, ppc)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (session['company_id'], d['month_idx'], d['date_str'], d['product'],
         d['weight'], d['esg'], d['service_life'], d['exposure_p'],
         d['proc_w'], d['esg_g'], d['ppc']))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return jsonify({'ok': True, 'id': new_id})

@app.route('/api/ppc/<int:entry_id>', methods=['PUT'])
@login_required
def update_ppc(entry_id):
    d = request.get_json()
    conn = get_db()
    conn.execute('''UPDATE ppc_entries SET
        date_str=?, product=?, weight=?, esg=?,
        service_life=?, exposure_p=?, proc_w=?, esg_g=?, ppc=?
        WHERE id=? AND company_id=?''',
        (d['date_str'], d['product'], d['weight'], d['esg'],
         d['service_life'], d['exposure_p'], d['proc_w'], d['esg_g'], d['ppc'],
         entry_id, session['company_id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/ppc/<int:entry_id>', methods=['DELETE'])
@login_required
def delete_ppc(entry_id):
    conn = get_db()
    conn.execute('DELETE FROM ppc_entries WHERE id=? AND company_id=?',
                 (entry_id, session['company_id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ──────────────────────────────────────────────
# ADMIN API — COMPANIES
# ──────────────────────────────────────────────
@app.route('/api/admin/companies', methods=['GET'])
@admin_required
def admin_companies():
    conn = get_db()
    companies = conn.execute('''
        SELECT c.id, c.company_name, c.email, c.created_at, c.is_verified, c.is_admin,
               COUNT(DISTINCT p.id) as pcc_count,
               COUNT(DISTINCT q.id) as ppc_count,
               COALESCE(SUM(p.pcc),0) as total_pcc,
               COALESCE(SUM(q.ppc),0) as total_ppc,
               COALESCE(SUM(p.weight),0)*430 + COALESCE(SUM(q.weight*CASE q.product
                 WHEN 'Bottle-to-bottle PET' THEN 1700
                 WHEN 'Reusable shopping bag' THEN 1800
                 WHEN 'Polyester apparel' THEN 1800
                 WHEN 'Blanket / Comforter' THEN 430
                 WHEN 'Carpet / Rug' THEN 430
                 WHEN 'Geotextile' THEN 430
                 WHEN 'Plastic crate' THEN 430
                 WHEN 'WPC panel' THEN 250
                 WHEN 'Road construction' THEN 250
                 ELSE 430 END),0) as total_co2
        FROM companies c
        LEFT JOIN pcc_entries p ON p.company_id = c.id
        LEFT JOIN ppc_entries q ON q.company_id = c.id
        WHERE c.email != 'gandhijidaksh@gmail.com'
        GROUP BY c.id
        ORDER BY c.created_at DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in companies])

@app.route('/api/admin/companies/<int:company_id>', methods=['PUT'])
@admin_required
def admin_update_company(company_id):
    d = request.get_json()
    conn = get_db()
    conn.execute('UPDATE companies SET company_name=?, email=? WHERE id=?',
                 (d['company_name'], d['email'], company_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/companies/<int:company_id>', methods=['DELETE'])
@admin_required
def admin_delete_company(company_id):
    conn = get_db()
    # Delete all entries first
    conn.execute('DELETE FROM pcc_entries WHERE company_id=?', (company_id,))
    conn.execute('DELETE FROM ppc_entries WHERE company_id=?', (company_id,))
    conn.execute('DELETE FROM companies WHERE id=?', (company_id,))
    conn.commit()
    conn.close()
    log_action(None, 'Admin', 'gandhijidaksh@gmail.com', f'deleted_company_{company_id}')
    return jsonify({'ok': True})

@app.route('/api/admin/companies/<int:company_id>/reset-password', methods=['POST'])
@admin_required
def admin_reset_password(company_id):
    d = request.get_json()
    new_password = d.get('password', '')
    if len(new_password) < 6:
        return jsonify({'ok': False, 'error': 'Password must be at least 6 characters.'})
    conn = get_db()
    conn.execute('UPDATE companies SET password=? WHERE id=?',
                 (generate_password_hash(new_password), company_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ──────────────────────────────────────────────
# ADMIN API — LOGS
# ──────────────────────────────────────────────
@app.route('/api/admin/logs', methods=['GET'])
@admin_required
def admin_logs():
    conn = get_db()
    logs = conn.execute(
        'SELECT * FROM access_log ORDER BY timestamp DESC LIMIT 200'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in logs])

@app.route('/api/admin/logs', methods=['DELETE'])
@admin_required
def admin_clear_logs():
    conn = get_db()
    conn.execute('DELETE FROM access_log')
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ──────────────────────────────────────────────
# ADMIN API — SUMMARY
# ──────────────────────────────────────────────
@app.route('/api/admin/summary', methods=['GET'])
@admin_required
def admin_summary():
    conn = get_db()
    total_companies = conn.execute(
        "SELECT COUNT(*) as n FROM companies WHERE email != 'gandhijidaksh@gmail.com'"
    ).fetchone()['n']
    total_pcc = conn.execute('SELECT COALESCE(SUM(pcc),0) as s FROM pcc_entries').fetchone()['s']
    total_ppc = conn.execute('SELECT COALESCE(SUM(ppc),0) as s FROM ppc_entries').fetchone()['s']
    total_logins = conn.execute(
        "SELECT COUNT(*) as n FROM access_log WHERE action='logged_in'"
    ).fetchone()['n']
    conn.close()
    return jsonify({
        'total_companies': total_companies,
        'total_pcc': round(total_pcc, 4),
        'total_ppc': round(total_ppc, 4),
        'total_logins': total_logins
    })

# ──────────────────────────────────────────────
# ADMIN API — COMPANY REPORT
# ──────────────────────────────────────────────
@app.route('/api/admin/report/<int:company_id>/json', methods=['GET'])
@admin_required
def admin_company_report(company_id):
    conn = get_db()
    company = conn.execute('SELECT * FROM companies WHERE id=?', (company_id,)).fetchone()
    if not company:
        conn.close()
        return jsonify({'error': 'Company not found'}), 404

    pcc_rows = conn.execute(
        'SELECT * FROM pcc_entries WHERE company_id=? ORDER BY month_idx, id',
        (company_id,)
    ).fetchall()
    ppc_rows = conn.execute(
        'SELECT * FROM ppc_entries WHERE company_id=? ORDER BY month_idx, id',
        (company_id,)
    ).fetchall()
    conn.close()

    MONTHS = ['January','February','March','April','May','June',
              'July','August','September','October','November','December']

    CO2_RATES = {
        'Bottle-to-bottle PET': 1700, 'Reusable shopping bag': 1800,
        'Polyester apparel': 1800, 'Blanket / Comforter': 430,
        'Carpet / Rug': 430, 'Geotextile': 430,
        'Plastic crate': 430, 'WPC panel': 250, 'Road construction': 250
    }
    CO2_RATE_PCC = 430
    pcc_list = [dict(r) for r in pcc_rows]
    ppc_list = [dict(r) for r in ppc_rows]
    total_co2 = sum(r['weight'] * CO2_RATE_PCC for r in pcc_list)
    total_co2 += sum(r['weight'] * CO2_RATES.get(r['product'], 430) for r in ppc_list)

    return jsonify({
        'company': dict(company),
        'pcc': pcc_list,
        'ppc': ppc_list,
        'months': MONTHS,
        'total_co2': round(total_co2, 2)
    })


# ──────────────────────────────────────────────
# ADMIN API — PROMOTE / DEMOTE ADMIN
# ──────────────────────────────────────────────
@app.route('/api/admin/companies/<int:company_id>/set-admin', methods=['POST'])
@admin_required
def admin_set_admin(company_id):
    # Only the superadmin can promote/demote
    if session.get('email') != 'gandhijidaksh@gmail.com':
        return jsonify({'ok': False, 'error': 'Only the superadmin can promote/demote admins.'})
    d = request.get_json()
    is_admin = 1 if d.get('is_admin') else 0
    conn = get_db()
    conn.execute('UPDATE companies SET is_admin=? WHERE id=?', (is_admin, company_id))
    conn.commit()
    conn.close()
    action = 'promoted_to_admin' if is_admin else 'demoted_from_admin'
    log_action(None, 'Admin', session.get('email'), f'{action}_{company_id}')
    return jsonify({'ok': True})


# ──────────────────────────────────────────────
# ADMIN API — CREATE ADMIN
# ──────────────────────────────────────────────
@app.route('/api/admin/create-admin', methods=['POST'])
@admin_required
def create_admin():
    d = request.get_json()
    name     = d.get('name', '').strip()
    email    = d.get('email', '').strip().lower()
    password = d.get('password', '')

    if not name or not email or not password:
        return jsonify({'ok': False, 'error': 'All fields are required.'})
    if len(password) < 6:
        return jsonify({'ok': False, 'error': 'Password must be at least 6 characters.'})

    conn = get_db()
    existing = conn.execute('SELECT id FROM companies WHERE email=?', (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'ok': False, 'error': 'An account with this email already exists.'})

    conn.execute('''INSERT INTO companies (company_name, email, password, is_verified, is_admin)
                    VALUES (?, ?, ?, 1, 1)''',
                 (name, email, generate_password_hash(password)))
    conn.commit()
    conn.close()
    log_action(None, 'Admin', session.get('email'), f'created_admin_{email}')
    return jsonify({'ok': True})

# ──────────────────────────────────────────────
# ADMIN API — DELETE ADMIN
# ──────────────────────────────────────────────
@app.route('/api/admin/admins/<int:admin_id>', methods=['DELETE'])
@admin_required
def delete_admin(admin_id):
    conn = get_db()
    admin = conn.execute('SELECT email FROM companies WHERE id=?', (admin_id,)).fetchone()
    if admin and admin['email'] == 'gandhijidaksh@gmail.com':
        conn.close()
        return jsonify({'ok': False, 'error': 'Cannot delete the superadmin account.'})
    conn.execute('DELETE FROM companies WHERE id=? AND is_admin=1', (admin_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ──────────────────────────────────────────────
# ADMIN API — LIST ADMINS
# ──────────────────────────────────────────────
@app.route('/api/admin/admins', methods=['GET'])
@admin_required
def list_admins():
    conn = get_db()
    admins = conn.execute(
        "SELECT id, company_name, email, created_at FROM companies WHERE is_admin=1 ORDER BY created_at"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in admins])


@app.route('/api/admin/settings', methods=['GET'])
@admin_required
def admin_get_settings():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    settings = {r['key']: r['value'] for r in rows}
    # Never send password back in plaintext
    settings['smtp_password'] = '••••••••' if settings.get('smtp_password') else ''
    return jsonify(settings)

@app.route('/api/admin/settings', methods=['POST'])
@admin_required
def admin_update_settings():
    d = request.get_json()
    conn = get_db()
    for key in ['smtp_email', 'smtp_host', 'smtp_port']:
        if key in d:
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)',
                         (key, d[key]))
    # Only update password if a new one is provided (not the masked placeholder)
    if d.get('smtp_password') and d['smtp_password'] != '••••••••':
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)',
                     ('smtp_password', d['smtp_password']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ──────────────────────────────────────────────
# ADMIN API — TEST EMAIL
# ──────────────────────────────────────────────
@app.route('/api/admin/test-email', methods=['POST'])
@admin_required
def admin_test_email():
    sent = send_email('gandhijidaksh@gmail.com',
                      'PET Credit Portal — Email Test',
                      '<h2>✅ Email is working correctly.</h2>')
    return jsonify({'ok': sent, 'message': 'Test email sent!' if sent else 'Failed — check SMTP settings.'})

# ──────────────────────────────────────────────
# RUN
# ──────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    print("\n✅ PET Plastic Credit Portal running at http://127.0.0.1:5000")
    print("   Admin login: gandhijidaksh@gmail.com / admin123\n")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)