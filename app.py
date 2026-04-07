"""
Indian PET Plastic Credit Framework
Flask Backend — app.py (Supabase/PostgreSQL version)
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import os, random, string
from datetime import datetime, timedelta
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pet-credit-iitdelhi-2026-xK9m2pQnv8')

import urllib.parse

def get_db():
    url = os.environ.get('DATABASE_URL', '')
    result = urllib.parse.urlparse(url)
    return psycopg2.connect(
        host=result.hostname,
        port=result.port or 6543,
        database=result.path[1:],
        user=result.username,
        password=urllib.parse.unquote(result.password or ''),
        sslmode='require'
    )

def fetchone(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    return {cursor.description[i][0]: row[i] for i in range(len(row))}

def fetchall(cursor):
    rows = cursor.fetchall()
    return [{cursor.description[i][0]: row[i] for i in range(len(row))} for row in rows]

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM companies WHERE email='gandhijidaksh@gmail.com'")
    existing = fetchone(c)
    if not existing:
        c.execute('''INSERT INTO companies (company_name, email, password, is_verified, is_admin)
                     VALUES (%s, %s, %s, 1, 1)''',
                  ('IIT Delhi Admin', 'gandhijidaksh@gmail.com',
                   generate_password_hash('admin123')))
    else:
        c.execute("UPDATE companies SET is_admin=1 WHERE email='gandhijidaksh@gmail.com'")
    conn.commit()
    conn.close()

def get_setting(key):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key=%s', (key,))
    row = fetchone(c)
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
        from email.utils import formataddr
        msg['From'] = formataddr(('IIT Delhi PET Credit Portal', smtp_email))
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
    expires_at = datetime.now() + timedelta(minutes=10)
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE otp_store SET used=1 WHERE email=%s AND purpose=%s', (email, purpose))
    c.execute('INSERT INTO otp_store (email, otp, purpose, expires_at) VALUES (%s,%s,%s,%s)',
              (email, otp, purpose, expires_at))
    conn.commit()
    conn.close()
    return otp

def verify_otp(email, otp, purpose):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT * FROM otp_store
        WHERE email=%s AND otp=%s AND purpose=%s AND used=0
        AND expires_at > NOW()
        ORDER BY id DESC LIMIT 1''', (email, otp, purpose))
    row = fetchone(c)
    if row:
        c.execute('UPDATE otp_store SET used=1 WHERE id=%s', (row['id'],))
        conn.commit()
    conn.close()
    return row is not None

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
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO access_log (company_id, company_name, email, action, ip_address)
                     VALUES (%s, %s, %s, %s, %s)''',
                  (company_id, company_name, email, action, request.remote_addr or 'unknown'))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'[LOG ERROR] {e}')

@app.route('/')
def index():
    if 'company_id' in session:
        if session.get('is_admin'):
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
    c = conn.cursor()
    c.execute('SELECT id FROM companies WHERE email=%s', (email,))
    if fetchone(c):
        conn.close()
        return jsonify({'ok': False, 'error': 'An account with this email already exists.'})
    c.execute('INSERT INTO companies (company_name, email, password, is_verified) VALUES (%s,%s,%s,0)',
              (company_name, email, generate_password_hash(password)))
    conn.commit()
    conn.close()
    otp = create_otp(email, 'verify')
    print(f'[VERIFY OTP for {email}]: {otp}')
    send_email(email, 'Verify your PET Credit Portal account',
        f'''<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;background:#0d1117;color:#e6edf3;border-radius:12px;">
        <h2 style="color:#1a9e8f;">♻️ PET Plastic Credit Portal</h2>
        <p style="margin-top:16px;">Your verification OTP is:</p>
        <div style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#1a9e8f;margin:20px 0;">{otp}</div>
        <p style="color:#8b949e;font-size:13px;">This OTP expires in 10 minutes. Do not share it.</p>
        </div>''')
    return jsonify({'ok': True, 'step': 'verify', 'email': email})

@app.route('/api/verify-registration', methods=['POST'])
def verify_registration():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()
    otp   = data.get('otp', '').strip()
    if not verify_otp(email, otp, 'verify'):
        return jsonify({'ok': False, 'error': 'Invalid or expired OTP. Please try again.'})
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE companies SET is_verified=1 WHERE email=%s', (email,))
    conn.commit()
    c.execute('SELECT * FROM companies WHERE email=%s', (email,))
    company = fetchone(c)
    conn.close()
    session['company_id']   = company['id']
    session['company_name'] = company['company_name']
    session['email']        = email
    session['is_admin']     = bool(company['is_admin'])
    log_action(company['id'], company['company_name'], email, 'registered')
    return jsonify({'ok': True, 'redirect': url_for('dashboard')})

@app.route('/api/login', methods=['POST'])
def login():
    data     = request.get_json()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM companies WHERE email=%s', (email,))
    company = fetchone(c)
    conn.close()
    if not company or not check_password_hash(company['password'], password):
        return jsonify({'ok': False, 'error': 'Invalid email or password.'})
    if company['is_admin']:
        session['company_id']   = company['id']
        session['company_name'] = company['company_name']
        session['email']        = email
        session['is_admin']     = True
        log_action(company['id'], company['company_name'], email, 'logged_in')
        return jsonify({'ok': True, 'redirect': url_for('admin_dashboard')})
    otp = create_otp(email, 'login')
    sent = send_email(email, 'Your PET Credit Portal login OTP',
        f'''<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;background:#0d1117;color:#e6edf3;border-radius:12px;">
        <h2 style="color:#1a9e8f;">♻️ PET Plastic Credit Portal</h2>
        <p style="margin-top:16px;">Your login OTP is:</p>
        <div style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#1a9e8f;margin:20px 0;">{otp}</div>
        <p style="color:#8b949e;font-size:13px;">This OTP expires in 10 minutes.</p>
        </div>''')
    if not sent:
        print(f'[LOGIN OTP for {email}]: {otp}')
    return jsonify({'ok': True, 'step': 'otp', 'email': email})

@app.route('/api/verify-login-otp', methods=['POST'])
def verify_login_otp():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()
    otp   = data.get('otp', '').strip()
    if not verify_otp(email, otp, 'login'):
        return jsonify({'ok': False, 'error': 'Invalid or expired OTP. Please try again.'})
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM companies WHERE email=%s', (email,))
    company = fetchone(c)
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

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM companies WHERE email=%s', (email,))
    company = fetchone(c)
    conn.close()
    if company:
        otp = create_otp(email, 'reset')
        print(f'[RESET OTP for {email}]: {otp}')
        send_email(email, 'Reset your PET Credit Portal password',
            f'''<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;background:#0d1117;color:#e6edf3;border-radius:12px;">
            <h2 style="color:#1a9e8f;">♻️ PET Plastic Credit Portal</h2>
            <p style="margin-top:16px;">Your password reset OTP is:</p>
            <div style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#1a9e8f;margin:20px 0;">{otp}</div>
            <p style="color:#8b949e;font-size:13px;">This OTP expires in 10 minutes.</p>
            </div>''')
    return jsonify({'ok': True, 'message': f'If {email} is registered, a reset OTP has been sent.'})

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
    c = conn.cursor()
    c.execute('UPDATE companies SET password=%s WHERE email=%s',
              (generate_password_hash(new_password), email))
    conn.commit()
    conn.close()
    log_action(None, None, email, 'password_reset')
    return jsonify({'ok': True, 'message': 'Password reset successfully. Please log in.'})

@app.route('/api/logout', methods=['POST'])
def logout():
    if 'company_id' in session:
        log_action(session['company_id'], session.get('company_name'),
                   session.get('email'), 'logged_out')
    session.clear()
    return jsonify({'ok': True, 'redirect': url_for('login_page')})

@app.route('/api/pcc', methods=['GET'])
@login_required
def get_pcc():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM pcc_entries WHERE company_id=%s ORDER BY month_idx, id',
              (session['company_id'],))
    rows = fetchall(c)
    conn.close()
    return jsonify(rows)

@app.route('/api/pcc', methods=['POST'])
@login_required
def add_pcc():
    d = request.get_json()
    conn = get_db()
    c = conn.cursor()
    record_date = datetime.now().strftime('%d %B %Y')
    c.execute('''INSERT INTO pcc_entries
        (company_id, month_idx, date_str, record_date, category, weight, esg, loc_f, eco_e, esg_g, pcc)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
        (session['company_id'], d['month_idx'], d['date_str'], record_date, d['category'],
         d['weight'], d['esg'], d['loc_f'], d['eco_e'], d['esg_g'], d['pcc']))
    new_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'id': new_id})

@app.route('/api/pcc/<int:entry_id>', methods=['PUT'])
@login_required
def update_pcc(entry_id):
    d = request.get_json()
    conn = get_db()
    c = conn.cursor()
    c.execute('''UPDATE pcc_entries SET
        date_str=%s, category=%s, weight=%s, esg=%s, loc_f=%s, eco_e=%s, esg_g=%s, pcc=%s
        WHERE id=%s AND company_id=%s''',
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
    c = conn.cursor()
    c.execute('DELETE FROM pcc_entries WHERE id=%s AND company_id=%s',
              (entry_id, session['company_id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/ppc', methods=['GET'])
@login_required
def get_ppc():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM ppc_entries WHERE company_id=%s ORDER BY month_idx, id',
              (session['company_id'],))
    rows = fetchall(c)
    conn.close()
    return jsonify(rows)

@app.route('/api/ppc', methods=['POST'])
@login_required
def add_ppc():
    d = request.get_json()
    conn = get_db()
    c = conn.cursor()
    record_date = datetime.now().strftime('%d %B %Y')
    c.execute('''INSERT INTO ppc_entries
        (company_id, month_idx, date_str, record_date, product, weight, esg,
         service_life, exposure_p, proc_w, esg_g, ppc)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
        (session['company_id'], d['month_idx'], d['date_str'], record_date, d['product'],
         d['weight'], d['esg'], d['service_life'], d['exposure_p'],
         d['proc_w'], d['esg_g'], d['ppc']))
    new_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'id': new_id})

@app.route('/api/ppc/<int:entry_id>', methods=['PUT'])
@login_required
def update_ppc(entry_id):
    d = request.get_json()
    conn = get_db()
    c = conn.cursor()
    c.execute('''UPDATE ppc_entries SET
        date_str=%s, product=%s, weight=%s, esg=%s,
        service_life=%s, exposure_p=%s, proc_w=%s, esg_g=%s, ppc=%s
        WHERE id=%s AND company_id=%s''',
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
    c = conn.cursor()
    c.execute('DELETE FROM ppc_entries WHERE id=%s AND company_id=%s',
              (entry_id, session['company_id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/companies', methods=['GET'])
@admin_required
def admin_companies():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT c.id, c.company_name, c.email, c.created_at, c.is_verified, c.is_admin,
               COUNT(DISTINCT p.id) as pcc_count,
               COUNT(DISTINCT q.id) as ppc_count,
               COALESCE(SUM(p.pcc),0) as total_pcc,
               COALESCE(SUM(q.ppc),0) as total_ppc,
               (SELECT COALESCE(SUM(weight),0)*430 FROM pcc_entries WHERE company_id=c.id) +
               (SELECT COALESCE(SUM(weight * CASE product
                 WHEN %s THEN 1700 WHEN %s THEN 1800 WHEN %s THEN 1800
                 WHEN %s THEN 430  WHEN %s THEN 430  WHEN %s THEN 430
                 WHEN %s THEN 430  WHEN %s THEN 250  WHEN %s THEN 250
                 ELSE 430 END),0) FROM ppc_entries WHERE company_id=c.id) as total_co2
        FROM companies c
        LEFT JOIN pcc_entries p ON p.company_id = c.id
        LEFT JOIN ppc_entries q ON q.company_id = c.id
        WHERE c.is_admin = 0
        GROUP BY c.id
        ORDER BY c.created_at DESC
    ''', ('Bottle-to-bottle PET','Reusable shopping bag','Polyester apparel',
          'Blanket / Comforter','Carpet / Rug','Geotextile',
          'Plastic crate','WPC panel','Road construction'))
    companies = fetchall(c)
    conn.close()
    for co in companies:
        if co.get('created_at'):
            co['created_at'] = str(co['created_at'])
    return jsonify(companies)

@app.route('/api/admin/companies/<int:company_id>', methods=['PUT'])
@admin_required
def admin_update_company(company_id):
    d = request.get_json()
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE companies SET company_name=%s, email=%s WHERE id=%s',
              (d['company_name'], d['email'], company_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/companies/<int:company_id>', methods=['DELETE'])
@admin_required
def admin_delete_company(company_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM pcc_entries WHERE company_id=%s', (company_id,))
    c.execute('DELETE FROM ppc_entries WHERE company_id=%s', (company_id,))
    c.execute('DELETE FROM companies WHERE id=%s', (company_id,))
    conn.commit()
    conn.close()
    log_action(None, 'Admin', session.get('email'), f'deleted_company_{company_id}')
    return jsonify({'ok': True})

@app.route('/api/admin/companies/<int:company_id>/reset-password', methods=['POST'])
@admin_required
def admin_reset_password(company_id):
    d = request.get_json()
    new_password = d.get('password', '')
    if len(new_password) < 6:
        return jsonify({'ok': False, 'error': 'Password must be at least 6 characters.'})
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE companies SET password=%s WHERE id=%s',
              (generate_password_hash(new_password), company_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/logs', methods=['GET'])
@admin_required
def admin_logs():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM access_log ORDER BY timestamp DESC LIMIT 200')
    logs = fetchall(c)
    conn.close()
    for log in logs:
        if log.get('timestamp'):
            log['timestamp'] = str(log['timestamp'])
    return jsonify(logs)

@app.route('/api/admin/logs', methods=['DELETE'])
@admin_required
def admin_clear_logs():
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM access_log')
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/summary', methods=['GET'])
@admin_required
def admin_summary():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as n FROM companies WHERE is_admin=0")
    total_companies = fetchone(c)['n']
    c.execute('SELECT COALESCE(SUM(pcc),0) as s FROM pcc_entries')
    total_pcc = fetchone(c)['s']
    c.execute('SELECT COALESCE(SUM(ppc),0) as s FROM ppc_entries')
    total_ppc = fetchone(c)['s']
    c.execute("SELECT COUNT(*) as n FROM access_log WHERE action='logged_in'")
    total_logins = fetchone(c)['n']
    conn.close()
    return jsonify({
        'total_companies': total_companies,
        'total_pcc': round(float(total_pcc), 4),
        'total_ppc': round(float(total_ppc), 4),
        'total_logins': total_logins
    })

@app.route('/api/admin/report/<int:company_id>/json', methods=['GET'])
@admin_required
def admin_company_report(company_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM companies WHERE id=%s', (company_id,))
    company = fetchone(c)
    if not company:
        conn.close()
        return jsonify({'error': 'Company not found'}), 404
    c.execute('SELECT * FROM pcc_entries WHERE company_id=%s ORDER BY month_idx, id', (company_id,))
    pcc_list = fetchall(c)
    c.execute('SELECT * FROM ppc_entries WHERE company_id=%s ORDER BY month_idx, id', (company_id,))
    ppc_list = fetchall(c)
    conn.close()
    MONTHS = ['January','February','March','April','May','June',
              'July','August','September','October','November','December']
    CO2_RATES = {'Bottle-to-bottle PET':1700,'Reusable shopping bag':1800,
                 'Polyester apparel':1800,'Blanket / Comforter':430,'Carpet / Rug':430,
                 'Geotextile':430,'Plastic crate':430,'WPC panel':250,'Road construction':250}
    total_co2 = sum(r['weight']*430 for r in pcc_list)
    total_co2 += sum(r['weight']*CO2_RATES.get(r['product'],430) for r in ppc_list)
    company = dict(company)
    if company.get('created_at'):
        company['created_at'] = str(company['created_at'])
    return jsonify({'company': company, 'pcc': pcc_list, 'ppc': ppc_list,
                    'months': MONTHS, 'total_co2': round(total_co2, 2)})

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
    c = conn.cursor()
    c.execute('SELECT id FROM companies WHERE email=%s', (email,))
    if fetchone(c):
        conn.close()
        return jsonify({'ok': False, 'error': 'An account with this email already exists.'})
    c.execute('INSERT INTO companies (company_name, email, password, is_verified, is_admin) VALUES (%s,%s,%s,1,1)',
              (name, email, generate_password_hash(password)))
    conn.commit()
    conn.close()
    log_action(None, 'Admin', session.get('email'), f'created_admin_{email}')
    return jsonify({'ok': True})

@app.route('/api/admin/admins/<int:admin_id>', methods=['DELETE'])
@admin_required
def delete_admin(admin_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT email FROM companies WHERE id=%s', (admin_id,))
    admin = fetchone(c)
    if admin and admin['email'] == 'gandhijidaksh@gmail.com':
        conn.close()
        return jsonify({'ok': False, 'error': 'Cannot delete the superadmin account.'})
    c.execute('DELETE FROM companies WHERE id=%s AND is_admin=1', (admin_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/admins', methods=['GET'])
@admin_required
def list_admins():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, company_name, email, created_at FROM companies WHERE is_admin=1 ORDER BY created_at")
    admins = fetchall(c)
    conn.close()
    for a in admins:
        if a.get('created_at'):
            a['created_at'] = str(a['created_at'])
    return jsonify(admins)

@app.route('/api/admin/settings', methods=['GET'])
@admin_required
def admin_get_settings():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT key, value FROM settings')
    rows = fetchall(c)
    conn.close()
    settings = {r['key']: r['value'] for r in rows}
    settings['smtp_password'] = '••••••••' if settings.get('smtp_password') else ''
    return jsonify(settings)

@app.route('/api/admin/settings', methods=['POST'])
@admin_required
def admin_update_settings():
    d = request.get_json()
    conn = get_db()
    c = conn.cursor()
    for key in ['smtp_email', 'smtp_host', 'smtp_port']:
        if key in d:
            c.execute('INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s',
                      (key, d[key], d[key]))
    if d.get('smtp_password') and d['smtp_password'] != '••••••••':
        c.execute('INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s',
                  ('smtp_password', d['smtp_password'], d['smtp_password']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/test-email', methods=['POST'])
@admin_required
def admin_test_email():
    sent = send_email('gandhijidaksh@gmail.com',
                      'PET Credit Portal — Email Test',
                      '<h2>✅ Email is working correctly.</h2>')
    return jsonify({'ok': sent, 'message': 'Test email sent!' if sent else 'Failed — check SMTP settings.'})

if __name__ == '__main__':
    init_db()
    print("\n✅ PET Plastic Credit Portal running at http://127.0.0.1:5000")
    print("   Admin login: gandhijidaksh@gmail.com / admin123\n")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)