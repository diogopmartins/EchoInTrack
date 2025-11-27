import json
from flask import Flask, render_template, jsonify, request, send_from_directory, session, redirect, url_for, send_file
from functools import wraps
import sqlite3
from datetime import datetime, timedelta, date
import os
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
import shutil
from apscheduler.schedulers.background import BackgroundScheduler

###############################################################################
# LOAD CONFIG
###############################################################################
CONFIG_FILE = 'config.json'

try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"ERROR: {CONFIG_FILE} not found. Please create it from config.json.example")
    raise
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON in {CONFIG_FILE}: {e}")
    raise

DB_PATH = config['db_path']                # e.g. "echo.db"
BACKUP_DIR = config['backup_dir']          # e.g. "backup"
MAX_BACKUPS = config['max_backups']        # e.g. 3
APP_PORT = config['port']                  # e.g. 5000

# Wards for the drop-down
WARD_OPTIONS = config.get('wards', [])

# Convert bank holiday list to a set for quick lookup
UK_BANK_HOLIDAYS = set(config['bank_holidays'])


###############################################################################
# FLASK APP SETUP
###############################################################################
app = Flask(__name__,
            static_url_path='',
            static_folder='static',
            template_folder='templates')
# Use environment variable for secret key, or generate one if not set
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())


###############################################################################
# WEEKEND / BANK HOLIDAY CHECK
###############################################################################
def is_weekend_or_bank_holiday(d: date) -> bool:
    """
    Return True if 'd' (a date object) is Saturday, Sunday,
    or is listed in the UK bank holidays set.
    """
    weekday = d.weekday()  # Monday=0, Sunday=6
    date_str = d.isoformat()  # 'YYYY-MM-DD'
    return (weekday == 5 or weekday == 6) or (date_str in UK_BANK_HOLIDAYS)


###############################################################################
# BACKUP LOGIC
###############################################################################
def get_uk_time():
    """
    Returns current time in the UK timezone (Europe/London).
    """
    return datetime.now(pytz.timezone('Europe/London'))

def backup_db():
    """
    Performs a safe backup of the SQLite database using SQLite's built-in backup method.
    Retains only the newest MAX_BACKUPS backups.
    """
    now_uk = get_uk_time()
    date_str = now_uk.strftime('%Y-%m-%d')
    time_str = now_uk.strftime('%H-%M')
    backup_filename = f"BACKUP-ECHO-IN-TRACK-{date_str}-{time_str}"

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        source_conn = sqlite3.connect(DB_PATH)
        dest_conn = sqlite3.connect(backup_path)
        source_conn.backup(dest_conn)

        dest_conn.close()
        source_conn.close()

        remove_old_backups()
    except Exception as e:
        print(f"Error performing backup: {e}")

def remove_old_backups():
    """
    Removes older backup files, keeping only the newest MAX_BACKUPS backups.
    """
    all_backups = []
    for fname in os.listdir(BACKUP_DIR):
        if fname.startswith("BACKUP-ECHO-IN-TRACK-"):
            full_path = os.path.join(BACKUP_DIR, fname)
            if os.path.isfile(full_path):
                all_backups.append((os.path.getmtime(full_path), full_path))

    all_backups.sort(key=lambda x: x[0], reverse=True)
    for _, path_to_delete in all_backups[MAX_BACKUPS:]:
        os.remove(path_to_delete)

# Schedule a backup at midnight (UK time)
scheduler = BackgroundScheduler()
scheduler.add_job(backup_db, 'cron', hour=0, minute=0, timezone='Europe/London')
scheduler.start()

def check_missed_backup():
    """
    Checks if there's no backup from yesterday or today; creates one if missing.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now_uk = get_uk_time()
    yesterday = now_uk.date() - timedelta(days=1)
    found_recent = False

    for fname in os.listdir(BACKUP_DIR):
        if fname.startswith("BACKUP-ECHO-IN-TRACK-"):
            parts = fname.split('-')
            if len(parts) >= 6:
                file_date_str = f"{parts[3]}-{parts[4]}-{parts[5]}"
                try:
                    file_date = datetime.strptime(file_date_str, "%Y-%m-%d").date()
                    if file_date in [now_uk.date(), yesterday]:
                        found_recent = True
                        break
                except ValueError:
                    pass

    if not found_recent:
        backup_db()


###############################################################################
# TIME / DB UTILS
###############################################################################
def convert_to_uk_time(dt):
    """
    Converts a naive or non-UK datetime object to UK (Europe/London) timezone.
    Returns None if dt is None or invalid.
    """
    if dt is None:
        return None
    if not dt.tzinfo:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(pytz.timezone('Europe/London'))

def uk_time_to_iso(dt):
    """
    Converts a datetime object to ISO format in UK timezone.
    Returns None if dt is None.
    """
    if dt is None:
        return None
    uk_dt = convert_to_uk_time(dt) if dt.tzinfo else pytz.timezone('Europe/London').localize(dt)
    return uk_dt.isoformat()

def iso_to_uk_time(iso_str):
    """
    Converts ISO string to a datetime object in UK timezone.
    Returns None if iso_str is empty or invalid.
    """
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return convert_to_uk_time(dt)
    except (ValueError, TypeError):
        return None

def format_uk_datetime(dt):
    """
    Formats a datetime object (or ISO string) into a DD/MM/YYYY @ HH:MM string.
    Returns empty string if invalid.
    """
    if not dt:
        return ""
    uk_dt = convert_to_uk_time(dt) if isinstance(dt, datetime) else iso_to_uk_time(dt)
    return uk_dt.strftime('%d/%m/%Y @ %H:%M') if uk_dt else ""

def add_working_hours_uk(start_date, hours):
    """
    Adds 'hours' hours to 'start_date', skipping weekends and bank holidays
    hour by hour. Returns the resulting datetime object.
    """
    if not start_date.tzinfo:
        start_date = pytz.timezone('Europe/London').localize(start_date)

    current_date = start_date
    remaining_hours = hours
    while remaining_hours > 0:
        current_date += timedelta(hours=1)
        day_obj = current_date.date()
        if not is_weekend_or_bank_holiday(day_obj):
            remaining_hours -= 1
    return current_date


###############################################################################
# FLASK SETUP / DECORATORS
###############################################################################
def init_db():
    """
    Initializes the database with 'users' and 'echo_requests' tables if they
    don't exist. Inserts default admin user if no users exist.
    Also ensures the 'notes', 'name', 'mrn', 'ward' columns exist in 'echo_requests'.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create tables if not exists
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS echo_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            pathway TEXT NOT NULL,
            request_time TIMESTAMP NOT NULL,
            expected_time TIMESTAMP,
            status TEXT DEFAULT 'pending',
            triage_date DATE NOT NULL,
            completion_time TIMESTAMP
        )
    ''')

    # Check existing columns
    c.execute("PRAGMA table_info(echo_requests)")
    columns = [info[1] for info in c.fetchall()]

    # Add notes if missing
    if 'notes' not in columns:
        try:
            c.execute("ALTER TABLE echo_requests ADD COLUMN notes TEXT DEFAULT ''")
        except Exception as e:
            print("Error adding notes column:", e)

    # Add name if missing
    if 'name' not in columns:
        try:
            c.execute("ALTER TABLE echo_requests ADD COLUMN name TEXT DEFAULT ''")
        except Exception as e:
            print("Error adding name column:", e)

    # Add mrn if missing
    if 'mrn' not in columns:
        try:
            c.execute("ALTER TABLE echo_requests ADD COLUMN mrn TEXT DEFAULT ''")
        except Exception as e:
            print("Error adding mrn column:", e)

    # Add ward if missing
    if 'ward' not in columns:
        try:
            c.execute("ALTER TABLE echo_requests ADD COLUMN ward TEXT DEFAULT ''")
        except Exception as e:
            print("Error adding ward column:", e)

    # Insert default user if none exist and ADMIN_PASSWORD is set
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        admin_password = os.environ.get('ADMIN_PASSWORD')
        if admin_password:
            default_password = generate_password_hash(admin_password)
            c.execute('INSERT INTO users (username, password) VALUES (?, ?)', ('admin', default_password))
            print("Admin user created successfully.")
        else:
            print("WARNING: No ADMIN_PASSWORD environment variable set. Admin user not created.")
            print("Set ADMIN_PASSWORD environment variable to create the default admin user.")

    conn.commit()
    conn.close()

def login_required(f):
    """
    Decorator that checks if the user is logged in. If not, redirects to login.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


###############################################################################
# ROUTES
###############################################################################
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Logs a user in by verifying credentials against the 'users' table.
    """
    if request.method == 'POST':
        try:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            if not username or not password:
                return render_template('login.html', error="Username and password are required")

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('SELECT id, password FROM users WHERE username = ?', (username,))
            user = c.fetchone()
            conn.close()

            if user and check_password_hash(user[1], password):
                session['user_id'] = user[0]
                return redirect(url_for('index'))
            else:
                return render_template('login.html', error="Invalid username or password")
        except Exception as e:
            app.logger.error(f"Error during login: {str(e)}")
            return render_template('login.html', error="An error occurred during login")

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    """
    Logs the user out by clearing session data.
    """
    session.clear()
    return jsonify({'message': 'Logged out successfully'}), 200

@app.route('/dashboard')
@login_required
def dashboard():
    """
    Renders the dashboard page, passing WARD_OPTIONS and bank holidays from config.json.
    """
    return render_template('dashboard.html',
                           wards=WARD_OPTIONS,
                           bank_holidays=config['bank_holidays'])

@app.route('/raw')
@login_required
def show_raw_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    now_str = datetime.now().isoformat()
    cursor.execute("""
        SELECT
            id,
            request_id,
            CASE WHEN pathway = 'REJECTED' THEN 'GREEN PATHWAY' ELSE pathway END as pathway,
            request_time,
            expected_time,
            status,
            completion_time,
            CASE
                WHEN
                    (
                        status='completed'
                        AND datetime(completion_time) > datetime(expected_time)
                    )
                    OR
                    (
                        status='pending'
                        AND datetime(expected_time) < datetime(?)
                    )
                THEN 'overdue'
                ELSE 'on_time'
            END AS performance,
            notes,
            name,
            mrn,
            ward
        FROM echo_requests
        ORDER BY id DESC
    """, (now_str,))

    echo_requests = cursor.fetchall()
    conn.close()

    # Pass wards=WARD_OPTIONS so raw.html can access it
    return render_template('raw.html', echo_requests=echo_requests, wards=WARD_OPTIONS)


@app.route('/static/<path:filename>')
def serve_static_files(filename):
    """
    Serves static files (CSS, JS, PDFs, images).
    """
    return send_from_directory('static', filename)

@app.route('/get_sentences')
@login_required
def get_sentences():
    """
    Reads and returns the contents of 'sentences.txt' for triage usage.
    """
    try:
        with open('sentences.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        app.logger.error("sentences.txt file not found")
        return "Error: sentences.txt file not found", 404
    except Exception as e:
        app.logger.error(f"Error reading sentences.txt: {str(e)}")
        return f"Error reading sentences file: {str(e)}", 500

@app.route('/api/add_request', methods=['POST'])
@login_required
def add_request():
    """
    API endpoint to add a new echo request.
    Returns the generated request_id as JSON.
    """
    try:
        data = request.json
        if not data or 'pathway' not in data or 'request_time' not in data:
            return jsonify({'error': 'Invalid request data. Missing required fields.'}), 400
        
        # Validate pathway
        valid_pathways = ['PURPLE PATHWAY', 'RED PATHWAY', 'AMBER PATHWAY', 'GREEN PATHWAY', 'REJECTED']
        if data['pathway'] not in valid_pathways:
            return jsonify({'error': f'Invalid pathway. Must be one of: {", ".join(valid_pathways)}'}), 400
        
        request_id = get_next_request_id()
        current_time = get_uk_time()
        triage_date = current_time.date()

        request_time = iso_to_uk_time(data['request_time'])
        if not request_time:
            return jsonify({'error': 'Invalid request_time format'}), 400
        
        expected_time = request_time

        if data['pathway'] == 'PURPLE PATHWAY':
            expected_time = add_working_hours_uk(request_time, 1)
        elif data['pathway'] == 'RED PATHWAY':
            expected_time = add_working_hours_uk(request_time, 24)
        elif data['pathway'] == 'AMBER PATHWAY':
            expected_time = add_working_hours_uk(request_time, 72)

        # Get name / mrn / ward if provided
        name_val = data.get('name', '')
        mrn_val = data.get('mrn', '')
        ward_val = data.get('ward', '')

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO echo_requests (request_id, pathway, request_time, expected_time, triage_date, notes, name, mrn, ward)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            request_id,
            data['pathway'],
            uk_time_to_iso(request_time),
            uk_time_to_iso(expected_time),
            triage_date,
            "",  # default blank notes
            name_val,
            mrn_val,
            ward_val
        ))
        conn.commit()
        conn.close()
        return jsonify({'request_id': request_id})
    except Exception as e:
        app.logger.error(f"Error adding request: {str(e)}")
        return jsonify({'error': 'Failed to add request'}), 500

def get_next_request_id():
    """
    Generates a new request ID in the format 'YY.0001',
    where 'YY' is the last two digits of the current year.
    """
    current_year = datetime.now().year % 100
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT request_id FROM echo_requests WHERE request_id LIKE ? ORDER BY request_id DESC LIMIT 1", (f"{current_year}.%",))
    row = c.fetchone()
    conn.close()

    if row is None:
        return f"{current_year}.{str(1).zfill(4)}"
    else:
        last_request_id = row[0]
        parts = last_request_id.split(".")
        last_seq = int(parts[1])
        new_seq = last_seq + 1
        return f"{current_year}.{str(new_seq).zfill(4)}"

@app.template_filter('format_datetime')
def format_datetime_filter(value):
    """
    Jinja2 filter that formats a datetime object (or ISO string)
    into a more readable UK datetime format.
    """
    return format_uk_datetime(value)

@app.route('/api/get_requests')
@login_required
def get_requests():
    """
    Returns all requests in JSON, with ordering:
    1) active pending (except green),
    2) green or rejected,
    3) completed.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute('''
        WITH ordered_requests AS (
            SELECT *,
                CASE
                    WHEN status = 'pending' AND pathway NOT IN ('GREEN PATHWAY')
                    THEN julianday(expected_time) - julianday(?)
                END as time_left
            FROM echo_requests
        )
        SELECT
            id,
            request_id,
            CASE WHEN pathway = 'REJECTED' THEN 'GREEN PATHWAY' ELSE pathway END as pathway,
            request_time,
            expected_time,
            status,
            triage_date,
            completion_time,
            notes,
            name,
            mrn,
            ward
        FROM ordered_requests
        ORDER BY
            CASE
                WHEN status = 'completed' THEN 3
                WHEN pathway IN ('GREEN PATHWAY', 'REJECTED') THEN 2
                ELSE 1
            END,
            CASE
                WHEN status = 'completed' THEN NULL
                WHEN pathway IN ('GREEN PATHWAY', 'REJECTED') THEN NULL
                ELSE time_left
            END ASC NULLS LAST,
            CASE
                WHEN status = 'completed' THEN completion_time
                WHEN pathway IN ('GREEN PATHWAY', 'REJECTED') THEN CAST(request_id AS INTEGER)
            END DESC
    ''', (now,))

    rows = c.fetchall()
    requests_list = []
    for r in rows:
        requests_list.append({
            'id': r[0],
            'request_id': r[1],
            'pathway': r[2],
            'request_time': r[3],
            'expected_time': r[4],
            'status': r[5],
            'triage_date': r[6],
            'completion_time': r[7],
            'notes': r[8],
            'name': r[9],
            'mrn': r[10],
            'ward': r[11]
        })

    conn.close()
    return jsonify(requests_list)

@app.route('/api/get_daily_stats')
@login_required
def get_daily_stats():
    """
    Returns JSON of the daily count of each pathway in the last 14 days,
    plus how many were performed (completed) each day.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    uk_now = get_uk_time()
    end_date = uk_now.date()
    start_date = end_date - timedelta(days=30)
    end_date_str = end_date.strftime('%Y-%m-%d')
    start_date_str = start_date.strftime('%Y-%m-%d')

    c.execute('''
        SELECT
            strftime('%Y-%m-%d', triage_date) as date,
            pathway,
            COUNT(*) as count
        FROM echo_requests
        WHERE date(triage_date) >= date(?) AND date(triage_date) <= date(?)
        GROUP BY strftime('%Y-%m-%d', triage_date), pathway
    ''', (start_date_str, end_date_str))
    pathway_results = c.fetchall()

    c.execute('''
        SELECT
            strftime('%Y-%m-%d', completion_time) as date,
            COUNT(*) as count
        FROM echo_requests
        WHERE status = 'completed'
          AND date(completion_time) >= date(?)
          AND date(completion_time) <= date(?)
        GROUP BY strftime('%Y-%m-%d', completion_time)
    ''', (start_date_str, end_date_str))
    completed_results = c.fetchall()

    stats = {}
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        stats[date_str] = {
            'PURPLE PATHWAY': 0,
            'RED PATHWAY': 0,
            'AMBER PATHWAY': 0,
            'GREEN PATHWAY': 0,
            'REJECTED': 0,
            'PERFORMED': 0
        }
        current_date += timedelta(days=1)

    for date_str, pathway, count in pathway_results:
        if date_str in stats:
            stats[date_str][pathway] = count

    for date_str, count in completed_results:
        if date_str in stats:
            stats[date_str]['PERFORMED'] = count

    conn.close()
    return jsonify(stats)

@app.route('/api/get_daily_overdue')
@login_required
def get_daily_overdue():
    """
    Returns JSON of how many were overdue each day in the last 14 days.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)

    c.execute('''
        WITH RECURSIVE dates(date) AS (
            SELECT date(?)
            UNION ALL
            SELECT date(date, '+1 day')
            FROM dates
            WHERE date < date(?)
        )
        SELECT
            strftime('%Y-%m-%d', dates.date) as the_date,
            COUNT(DISTINCT r.id) as overdue_count
        FROM dates
        LEFT JOIN echo_requests r
            ON r.pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
            AND datetime(r.expected_time) < datetime(dates.date, '+1 day')
            AND datetime(r.request_time) <= datetime(dates.date, '+1 day')
            AND (
                (r.status = 'pending')
                OR
                (r.status = 'completed' AND datetime(r.completion_time) > datetime(dates.date))
                OR
                (
                  r.status = 'completed'
                  AND datetime(r.completion_time) >= datetime(dates.date)
                  AND datetime(r.completion_time) < datetime(dates.date, '+1 day')
                  AND datetime(r.completion_time) > datetime(r.expected_time)
                )
            )
        GROUP BY the_date
        ORDER BY the_date
    ''', (start_date, end_date))
    results = c.fetchall()
    conn.close()

    overdue_counts = {}
    for day_str, count in results:
        overdue_counts[day_str] = count

    return jsonify(overdue_counts)

@app.route('/api/get_overdue_count')
@login_required
def get_overdue_count():
    """
    Returns the count of all currently overdue requests.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute('''
        SELECT COUNT(*) as overdue_count
        FROM echo_requests
        WHERE status = 'pending'
          AND pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
          AND datetime(expected_time) < datetime(?)
          AND datetime(request_time) <= datetime(?)
    ''', (now, now))
    overdue_count = c.fetchone()[0]
    conn.close()
    return jsonify({'overdue_count': overdue_count})

@app.route('/api/get_daily_max_pending')
@login_required
def get_daily_max_pending():
    """
    Returns JSON of the maximum number of pending requests each day in the last 14 days.
    This counts requests that were pending at any point during each day.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)

    c.execute('''
        WITH RECURSIVE dates(date) AS (
            SELECT date(?)
            UNION ALL
            SELECT date(date, '+1 day')
            FROM dates
            WHERE date < date(?)
        )
        SELECT
            strftime('%Y-%m-%d', dates.date) as the_date,
            COUNT(DISTINCT r.id) as pending_count
        FROM dates
        LEFT JOIN echo_requests r
            ON r.pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
            AND datetime(r.request_time) <= datetime(dates.date, '+1 day')
            AND (
                r.status = 'pending'
                OR
                datetime(r.completion_time) >= datetime(dates.date)
            )
        GROUP BY the_date
        ORDER BY the_date
    ''', (start_date, end_date))
    results = c.fetchall()
    conn.close()

    pending_counts = {}
    for day_str, count in results:
        pending_counts[day_str] = count

    return jsonify(pending_counts)

@app.route('/api/get_today_stats')
@login_required
def get_today_stats():
    """
    Returns today's stats: how many in each pathway, performed today, and overdue.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute('''
        SELECT pathway, COUNT(*) as count
        FROM echo_requests
        WHERE status = 'pending'
          AND pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
        GROUP BY pathway
    ''')
    results = c.fetchall()

    c.execute('''
        SELECT COUNT(*) as count
        FROM echo_requests
        WHERE DATE(completion_time) = DATE('now')
          AND status = 'completed'
    ''')
    completed_count = c.fetchone()[0]

    c.execute('''
        SELECT COUNT(*) as count
        FROM echo_requests
        WHERE (pathway = 'GREEN PATHWAY' OR pathway = 'REJECTED')
          AND DATE(request_time) = DATE('now')
    ''')
    green_count = c.fetchone()[0]

    c.execute('''
        SELECT COUNT(*) as overdue_count
        FROM echo_requests
        WHERE status = 'pending'
          AND pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
          AND datetime(expected_time) < datetime(?)
    ''', (now,))
    overdue_count = c.fetchone()[0]

    conn.close()

    counts = {
        'PURPLE PATHWAY': 0,
        'RED PATHWAY': 0,
        'AMBER PATHWAY': 0,
        'GREEN PATHWAY': green_count,
        'PERFORMED': completed_count,
        'OVERDUE': overdue_count
    }
    for pathway, count in results:
        counts[pathway] = count

    return jsonify(counts)

@app.route('/api/get_average_completion_times')
@login_required
def get_average_completion_times():
    """
    Returns average completion times for purple, red, and amber pathways
    over the last 15 days, excluding weekend hours.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    uk_now = get_uk_time()
    end_date = uk_now.date()
    start_date = end_date - timedelta(days=30)

    c.execute('''
        SELECT 
            pathway,
            AVG(
                CASE 
                    WHEN strftime('%w', request_time) IN ('0', '6') 
                         OR strftime('%w', completion_time) IN ('0', '6')
                    THEN 0
                    ELSE (
                        (julianday(completion_time) - julianday(request_time)) * 24
                    )
                END
            ) as avg_hours
        FROM echo_requests
        WHERE status = 'completed'
            AND pathway IN ('PURPLE PATHWAY', 'RED PATHWAY', 'AMBER PATHWAY')
            AND date(completion_time) >= date(?)
            AND date(completion_time) <= date(?)
            AND completion_time IS NOT NULL
        GROUP BY pathway
    ''', (start_date, end_date))

    results = c.fetchall()
    conn.close()

    avg_times = {
        'PURPLE PATHWAY': 0,
        'RED PATHWAY': 0,
        'AMBER PATHWAY': 0
    }

    for pathway, avg_hours in results:
        if avg_hours:
            avg_times[pathway] = round(avg_hours)

    return jsonify(avg_times)

@app.route('/api/mark_completed', methods=['POST'])
@login_required
def mark_completed():
    """
    Marks a given request as 'completed' with the current UK time.
    """
    try:
        data = request.json
        if not data or 'id' not in data:
            return jsonify({'error': 'Invalid request data. Missing id.'}), 400
        
        request_id = data['id']
        completion_time = get_uk_time().isoformat()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE echo_requests
            SET status = 'completed', completion_time = ?
            WHERE id = ?
        ''', (completion_time, request_id))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"Error marking request as completed: {str(e)}")
        return jsonify({'error': 'Failed to mark request as completed'}), 500

@app.route('/api/delete_request', methods=['POST'])
@login_required
def delete_request():
    """
    Deletes a request from the database by its numeric ID.
    """
    try:
        data = request.json
        if not data or 'id' not in data:
            return jsonify({'error': 'Invalid request data. Missing id.'}), 400
        
        request_id = data['id']
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM echo_requests WHERE id = ?', (request_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"Error deleting request: {str(e)}")
        return jsonify({'error': 'Failed to delete request'}), 500

@app.route('/api/undo_completed', methods=['POST'])
@login_required
def undo_completed():
    """
    Reverts a completed request back to pending status.
    """
    try:
        data = request.json
        if not data or 'id' not in data:
            return jsonify({'error': 'Invalid request data. Missing id.'}), 400
        
        request_id = data['id']
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE echo_requests
            SET status = 'pending', completion_time = NULL
            WHERE id = ?
        ''', (request_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"Error undoing completion: {str(e)}")
        return jsonify({'error': 'Failed to undo completion'}), 500

# --------------- NEW NOTES ENDPOINT ---------------
@app.route('/api/update_notes', methods=['POST'])
@login_required
def update_notes():
    """
    Updates the notes field for a given echo request ID.
    Expects JSON: { "id": <request_id>, "notes": "<text>" }
    """
    try:
        data = request.json
        if not data or 'id' not in data:
            return jsonify({'error': 'Invalid request data. Missing id.'}), 400
        
        request_id = data.get('id')
        new_notes = data.get('notes', "")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE echo_requests
            SET notes = ?
            WHERE id = ?
        ''', (new_notes, request_id))
        conn.commit()
        conn.close()

        return jsonify({'status': 'success', 'notes': new_notes})
    except Exception as e:
        app.logger.error(f"Error updating notes: {str(e)}")
        return jsonify({'error': 'Failed to update notes'}), 500

# --------------- NEW FIELDS ENDPOINTS ---------------
@app.route('/api/update_name', methods=['POST'])
@login_required
def update_name():
    """
    Updates the 'name' field for a given echo request ID.
    Expects JSON: { "id": <request_id>, "name": "<text>" }
    """
    try:
        data = request.json
        if not data or 'id' not in data:
            return jsonify({'error': 'Invalid request data. Missing id.'}), 400
        
        request_id = data.get('id')
        new_name = data.get('name', "")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE echo_requests
            SET name = ?
            WHERE id = ?
        ''', (new_name, request_id))
        conn.commit()
        conn.close()

        return jsonify({'status': 'success', 'name': new_name})
    except Exception as e:
        app.logger.error(f"Error updating name: {str(e)}")
        return jsonify({'error': 'Failed to update name'}), 500

@app.route('/api/update_mrn', methods=['POST'])
@login_required
def update_mrn():
    """
    Updates the 'mrn' field for a given echo request ID.
    Expects JSON: { "id": <request_id>, "mrn": "<text>" }
    """
    try:
        data = request.json
        if not data or 'id' not in data:
            return jsonify({'error': 'Invalid request data. Missing id.'}), 400
        
        request_id = data.get('id')
        new_mrn = data.get('mrn', "")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE echo_requests
            SET mrn = ?
            WHERE id = ?
        ''', (new_mrn, request_id))
        conn.commit()
        conn.close()

        return jsonify({'status': 'success', 'mrn': new_mrn})
    except Exception as e:
        app.logger.error(f"Error updating MRN: {str(e)}")
        return jsonify({'error': 'Failed to update MRN'}), 500

@app.route('/api/update_ward', methods=['POST'])
@login_required
def update_ward():
    """
    Updates the 'ward' field for a given echo request ID.
    Expects JSON: { "id": <request_id>, "ward": "<option>" }
    """
    try:
        data = request.json
        if not data or 'id' not in data:
            return jsonify({'error': 'Invalid request data. Missing id.'}), 400
        
        request_id = data.get('id')
        new_ward = data.get('ward', "")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE echo_requests
            SET ward = ?
            WHERE id = ?
        ''', (new_ward, request_id))
        conn.commit()
        conn.close()

        return jsonify({'status': 'success', 'ward': new_ward})
    except Exception as e:
        app.logger.error(f"Error updating ward: {str(e)}")
        return jsonify({'error': 'Failed to update ward'}), 500


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """
    Allows the logged-in user to change their password,
    validating current password and matching new password fields.
    """
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT password FROM users WHERE id = ?', (session['user_id'],))
        user = c.fetchone()

        if not check_password_hash(user[0], current_password):
            return render_template('change_password.html', error='Current password is incorrect')

        if new_password != confirm_password:
            return render_template('change_password.html', error='New passwords do not match')

        hashed_password = generate_password_hash(new_password)
        c.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_password, session['user_id']))
        conn.commit()
        conn.close()

        return render_template('change_password.html', success='Password updated successfully')

    return render_template('change_password.html')

###############################################################################
# EDITOR ROUTES
###############################################################################
@app.route('/editor')
@login_required
def editor():
    """
    Renders an editor page to edit sentences.txt using CodeMirror.
    """
    return render_template('editor.html')


@app.route('/api/save_sentences', methods=['POST'])
@login_required
def save_sentences():
    """
    Saves edited content back into sentences.txt.
    Expects JSON body: { "content": "..." }
    """
    try:
        data = request.json
        if not data or 'content' not in data:
            return jsonify({'error': 'Invalid request data. Missing content.'}), 400
        
        content = data.get("content", "")

        with open('sentences.txt', 'w', encoding='utf-8') as f:
            f.write(content)

        return jsonify({"status": "success"})
    except Exception as e:
        app.logger.error(f"Error saving sentences.txt: {str(e)}")
        return jsonify({'error': 'Failed to save sentences file'}), 500


###############################################################################
# BACKUP MANAGEMENT ROUTES
###############################################################################
@app.route('/backup')
@login_required
def backup_management():
    """
    Renders the backup management page, showing current DB and backup files.
    """
    db_path = os.path.join(os.getcwd(), DB_PATH)
    current_db_stats = os.stat(db_path)

    now = get_uk_time()
    current_db = {
        'filename': f"CURRENT-ECHO-IN-TRACK-{now.strftime('%Y-%m-%d-%H-%M')}.db",
        'size': f"{current_db_stats.st_size / (1024 * 1024):.2f} MB",
        'modified': datetime.fromtimestamp(current_db_stats.st_mtime).strftime('%d/%m/%Y @ %H:%M')
    }

    backups = []
    for filename in os.listdir(BACKUP_DIR):
        if filename.startswith("BACKUP-ECHO-IN-TRACK-"):
            file_path = os.path.join(BACKUP_DIR, filename)
            stats = os.stat(file_path)
            backups.append({
                'filename': filename,
                'size': f"{stats.st_size / (1024 * 1024):.2f} MB",
                'created': datetime.fromtimestamp(stats.st_ctime).strftime('%d/%m/%Y @ %H:%M')
            })

    backups.sort(key=lambda x: x['filename'], reverse=True)

    return render_template('backup.html', current_db=current_db, backups=backups)

@app.route('/api/download_backup/<filename>')
@login_required
def download_backup(filename):
    """
    Handles downloading of backup files and current DB.
    """
    if filename.startswith("CURRENT-ECHO-IN-TRACK-"):
        try:
            return send_file(
                DB_PATH,
                mimetype='application/x-sqlite3',
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            app.logger.error(f"Error sending current database: {str(e)}")
            return "Error accessing database file", 500

    elif filename.startswith("BACKUP-ECHO-IN-TRACK-"):
        backup_path = os.path.join(os.getcwd(), BACKUP_DIR, filename)
        if os.path.exists(backup_path):
            try:
                return send_file(
                    backup_path,
                    mimetype='application/x-sqlite3',
                    as_attachment=True,
                    download_name=filename
                )
            except Exception as e:
                app.logger.error(f"Error sending backup file: {str(e)}")
                return "Error accessing backup file", 500

    return "File not found", 404

@app.route('/api/import_database', methods=['POST'])
@login_required
def import_database():
    """
    Handles database import/replacement.
    """
    if 'database' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['database']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.endswith('.db'):
        return jsonify({'error': 'Invalid file type'}), 400

    try:
        backup_db()
        file.save(DB_PATH)
        return jsonify({'message': 'Database successfully imported'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin')
@login_required
def admin_page():
    """
    Simple admin panel with links to various pages.
    """
    return render_template('admin.html')


###############################################################################
# MAIN
###############################################################################
if __name__ == '__main__':
    init_db()
    check_missed_backup()
    # Use environment variable for debug mode (default: False for security)
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', debug=DEBUG, port=APP_PORT)
