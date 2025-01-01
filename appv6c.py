from flask import Flask, render_template, jsonify, request, send_from_directory, session, redirect, url_for
from functools import wraps
import sqlite3
from datetime import datetime, timedelta
import os
from werkzeug.security import generate_password_hash, check_password_hash
import pytz

app = Flask(__name__)
app.secret_key = os.urandom(24)



def get_uk_time():
    """Get current time in UK timezone"""
    uk_tz = pytz.timezone('Europe/London')
    return datetime.now(uk_tz)


def convert_to_uk_time(dt):
    """Convert a datetime object to UK time"""
    if dt is None:
        return None

    if not dt.tzinfo:
        # If datetime is naive, assume it's UTC
        dt = pytz.UTC.localize(dt)

    uk_tz = pytz.timezone('Europe/London')
    return dt.astimezone(uk_tz)


def uk_time_to_iso(dt):
    """Convert UK time to ISO format string"""
    if dt is None:
        return None
    uk_dt = convert_to_uk_time(dt) if dt.tzinfo else pytz.timezone('Europe/London').localize(dt)
    return uk_dt.isoformat()


def iso_to_uk_time(iso_str):
    """Convert ISO string to UK datetime"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return convert_to_uk_time(dt)
    except (ValueError, TypeError):
        return None


def format_uk_datetime(dt):
    """Format datetime in UK format"""
    if not dt:
        return ""
    uk_dt = convert_to_uk_time(dt) if isinstance(dt, datetime) else iso_to_uk_time(dt)
    return uk_dt.strftime('%d/%m/%Y @ %H:%M') if uk_dt else ""


def add_working_hours_uk(start_date, hours):
    """Add working hours to a date, respecting UK timezone"""
    if not start_date.tzinfo:
        uk_tz = pytz.timezone('Europe/London')
        start_date = uk_tz.localize(start_date)

    current_date = start_date
    remaining_hours = hours

    while remaining_hours > 0:
        current_date += timedelta(hours=1)
        if current_date.weekday() < 5:  # Only count weekdays (Monday = 0, Friday = 4)
            remaining_hours -= 1

    return current_date

def init_db():
    conn = sqlite3.connect('echo.db')
    c = conn.cursor()

    # Create users table if it doesn't exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create the original echo_requests table if it doesn't exist
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

    # Add a default admin user if none exists
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        default_password = generate_password_hash('admin123')  # Change this default password
        c.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                  ('admin', default_password))

    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect('echo.db')
        c = conn.cursor()
        c.execute('SELECT id, password FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            return redirect(url_for('index'))

        return render_template('login.html', error='Invalid username or password')

    return render_template('login.html')


# Logout route
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()  # Clears session data
    return jsonify({'message': 'Logged out successfully'}), 200



def get_next_request_id():
    conn = sqlite3.connect('echo.db')
    c = conn.cursor()
    c.execute('SELECT MAX(request_id) FROM echo_requests')
    result = c.fetchone()[0]
    conn.close()

    if result is None:
        return "0001"
    else:
        return str(int(result) + 1).zfill(4)


def add_working_hours(start_date, hours):
    current_date = start_date
    remaining_hours = hours

    while remaining_hours > 0:
        current_date += timedelta(hours=1)
        if current_date.weekday() < 5:  # Only count weekdays (Monday = 0, Friday = 4)
            remaining_hours -= 1

    return current_date

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/raw')
@login_required
def show_raw_data():
    conn = sqlite3.connect('echo.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            id, 
            request_id, 
            CASE 
                WHEN pathway = 'REJECTED' THEN 'GREEN PATHWAY'
                ELSE pathway 
            END as pathway,
            request_time, 
            expected_time, 
            status, 
            completion_time
        FROM echo_requests
    """)
    echo_requests = cursor.fetchall()
    conn.close()
    return render_template('raw.html', echo_requests=echo_requests)


@app.route('/static/<path:filename>')
@login_required
def serve_static(filename):
    return send_from_directory('static', filename)


@app.route('/get_sentences')
@login_required
def get_sentences():
    with open('sentences.txt', 'r') as file:
        return file.read()


@app.route('/api/add_request', methods=['POST'])
@login_required
def add_request():
    data = request.json
    request_id = get_next_request_id()
    current_time = get_uk_time()
    triage_date = current_time.date()

    request_time = iso_to_uk_time(data['request_time'])
    expected_time = request_time

    if data['pathway'] == 'PURPLE PATHWAY':
        expected_time = add_working_hours_uk(request_time, 1)
    elif data['pathway'] == 'RED PATHWAY':
        expected_time = add_working_hours_uk(request_time, 24)
    elif data['pathway'] == 'AMBER PATHWAY':
        expected_time = add_working_hours_uk(request_time, 72)

    conn = sqlite3.connect('echo.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO echo_requests (request_id, pathway, request_time, expected_time, triage_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (request_id, data['pathway'], uk_time_to_iso(request_time),
          uk_time_to_iso(expected_time), triage_date))
    conn.commit()
    conn.close()
    return jsonify({'request_id': request_id})


@app.template_filter('format_datetime')
def format_datetime(value):
    return format_uk_datetime(value)

@app.route('/api/get_requests')
@login_required
def get_requests():
    conn = sqlite3.connect('echo.db')
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
            CASE 
                WHEN pathway = 'REJECTED' THEN 'GREEN PATHWAY'
                ELSE pathway 
            END as pathway,
            request_time,
            expected_time,
            status,
            triage_date,
            completion_time
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

    requests = [{'id': r[0],
                 'request_id': r[1],
                 'pathway': r[2],
                 'request_time': r[3],
                 'expected_time': r[4],
                 'status': r[5],
                 'triage_date': r[6],
                 'completion_time': r[7]}
                for r in c.fetchall()]
    conn.close()
    return jsonify(requests)


@app.route('/api/get_daily_stats')
@login_required
def get_daily_stats():
    conn = sqlite3.connect('echo.db')
    c = conn.cursor()

    # Get today's date in UK timezone
    uk_now = datetime.now(pytz.timezone('Europe/London'))
    end_date = uk_now.date()
    start_date = end_date - timedelta(days=14)

    # Format dates for SQLite
    end_date_str = end_date.strftime('%Y-%m-%d')
    start_date_str = start_date.strftime('%Y-%m-%d')

    # Get pathway counts
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

    # Get completed counts
    c.execute('''
        SELECT 
            strftime('%Y-%m-%d', completion_time) as date,
            COUNT(*) as count
        FROM echo_requests
        WHERE 
            status = 'completed' 
            AND date(completion_time) >= date(?) 
            AND date(completion_time) <= date(?)
        GROUP BY strftime('%Y-%m-%d', completion_time)
    ''', (start_date_str, end_date_str))
    completed_results = c.fetchall()

    # Get overdue counts
    c.execute('''
        WITH RECURSIVE dates(date) AS (
            SELECT date(?)
            UNION ALL
            SELECT date(date, '+1 day')
            FROM dates
            WHERE date < date(?)
        )
        SELECT 
            strftime('%Y-%m-%d', dates.date) as date,
            COUNT(DISTINCT CASE 
                WHEN r.pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
                AND datetime(r.expected_time) < datetime(dates.date, '+1 day')
                AND (
                    r.status = 'pending'
                    OR 
                    (r.status = 'completed' AND datetime(r.completion_time) > datetime(dates.date))
                )
                AND datetime(r.request_time) <= datetime(dates.date, '+1 day')
                THEN r.id 
            END) as count
        FROM dates
        LEFT JOIN echo_requests r ON 1=1
        GROUP BY dates.date
        ORDER BY dates.date
    ''', (start_date_str, end_date_str))
    overdue_results = c.fetchall()

    # Initialize stats dictionary
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
            'PERFORMED': 0,
            'OVERDUE': 0
        }
        current_date += timedelta(days=1)

    # Fill in the data
    for date, pathway, count in pathway_results:
        if date in stats:
            stats[date][pathway] = count

    for date, count in completed_results:
        if date in stats:
            stats[date]['PERFORMED'] = count

    for date, count in overdue_results:
        if date in stats:
            stats[date]['OVERDUE'] = count

    conn.close()
    return jsonify(stats)


@app.route('/api/get_overdue_count')
@login_required
def get_overdue_count():
    conn = sqlite3.connect('echo.db')
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

@app.route('/api/get_today_stats')
@login_required
def get_today_stats():
    conn = sqlite3.connect('echo.db')
    c = conn.cursor()
    today = datetime.now().date().isoformat()
    now = datetime.now().isoformat()

    # Get current pending counts for non-green pathways
    c.execute('''
        SELECT pathway, COUNT(*) as count
        FROM echo_requests
        WHERE status = 'pending'
        AND pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
        GROUP BY pathway
    ''')

    results = c.fetchall()

    # Get completed count for today
    c.execute('''
        SELECT COUNT(*) as count
        FROM echo_requests
        WHERE DATE(completion_time) = DATE('now')
        AND status = 'completed'
    ''')

    completed_count = c.fetchone()[0]

    # Get green pathway AND rejected requests from today only
    c.execute('''
        SELECT COUNT(*) as count
        FROM echo_requests
        WHERE (pathway = 'GREEN PATHWAY' OR pathway = 'REJECTED')
        AND DATE(request_time) = DATE('now')
    ''')

    green_count = c.fetchone()[0]

    # Get current overdue count
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

    # Add pathway counts
    for pathway, count in results:
        counts[pathway] = count

    return jsonify(counts)


@app.route('/api/mark_completed', methods=['POST'])
@login_required
def mark_completed():
    request_id = request.json['id']
    completion_time = get_uk_time().isoformat()  # Use get_uk_time() instead of datetime.now()
    conn = sqlite3.connect('echo.db')
    c = conn.cursor()
    c.execute('''
        UPDATE echo_requests 
        SET status = 'completed', completion_time = ?
        WHERE id = ?
    ''', (completion_time, request_id))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})


@app.route('/api/delete_request', methods=['POST'])
@login_required
def delete_request():
    request_id = request.json['id']
    conn = sqlite3.connect('echo.db')
    c = conn.cursor()
    c.execute('DELETE FROM echo_requests WHERE id = ?', (request_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})




@app.route('/api/undo_completed', methods=['POST'])
@login_required
def undo_completed():
    request_id = request.json['id']
    conn = sqlite3.connect('echo.db')
    c = conn.cursor()
    c.execute('''
        UPDATE echo_requests 
        SET status = 'pending', completion_time = NULL
        WHERE id = ?
    ''', (request_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})



# Custom Flask filter for datetime formatting
@app.template_filter('format_datetime')
@login_required
def format_datetime(value):
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime('%d/%m/%Y @ %H:%M')
    except (ValueError, TypeError):
        return value  # Return original value if conversion fails


@app.route('/api/get_daily_overdue')
@login_required
def get_daily_overdue():
    conn = sqlite3.connect('echo.db')
    c = conn.cursor()
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=14)

    # For each day, count requests that were overdue as of that day
    overdue_counts = {}

    for i in range(15):
        current_date = start_date + timedelta(days=i)
        next_date = current_date + timedelta(days=1)

        # Count requests that were:
        # 1. Pending or completed as of that day
        # 2. Not GREEN PATHWAY or REJECTED
        # 3. Had expected_time before the end of that day
        c.execute('''
            SELECT COUNT(*) FROM echo_requests
            WHERE pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
            AND datetime(expected_time) < datetime(?)
            AND (
                (status = 'pending')
                OR 
                (status = 'completed' AND datetime(completion_time) > datetime(?))
            )
            AND datetime(request_time) <= datetime(?)
        ''', (next_date.isoformat(), next_date.isoformat(), next_date.isoformat()))

        count = c.fetchone()[0]
        overdue_counts[current_date.isoformat()] = count

    conn.close()
    return jsonify(overdue_counts)


if __name__ == '__main__':
    init_db()
    app.run(debug=True)