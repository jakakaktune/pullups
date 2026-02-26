from flask import Flask, request, render_template, jsonify
import sqlite3
import datetime

app = Flask(__name__, static_folder='public', static_url_path='/public')
DB_PATH = 'pullups.sqlite'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  
    return conn

# Bootstrap the DB
with get_db() as conn:
    conn.execute('''CREATE TABLE IF NOT EXISTS sessions 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, total_reps INTEGER)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sets 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, reps INTEGER, 
                     duration_seconds INTEGER, rest_time_after INTEGER, FOREIGN KEY(session_id) REFERENCES sessions(id))''')

@app.route('/api/add-entry', methods=['POST'])
def add_entry():
    data = request.json
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("INSERT INTO sessions (total_reps) VALUES (?)", (data.get('total_reps', 0),))
        session_id = cursor.lastrowid
        
        for s in data.get('sets', []):
            reps = int(s.get('reps', 0))
            if reps > 0:
                cursor.execute("""INSERT INTO sets (session_id, reps, duration_seconds, rest_time_after) 
                                  VALUES (?, ?, ?, ?)""", 
                               (session_id, reps, s.get('duration_seconds', 0), s.get('rest_time_after', 0)))
        
        conn.commit()
        return jsonify({"success": True, "id": session_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/clean-db', methods=['POST'])
def clean_db():
    try:
        # Using a context manager automatically helps manage connections
        with get_db() as conn:
            cursor = conn.cursor()
            
            # The exact cutoff date in standard SQLite format (YYYY-MM-DD HH:MM:SS)
            # Since London is on GMT in February, UTC matches your local time exactly.
            cutoff_date = '2026-02-22 19:30:00'
            
            # 1. Clean up any 0-rep sets
            cursor.execute("DELETE FROM sets WHERE reps = 0")
            
            # 2. Delete the child records (sets) for old sessions
            cursor.execute("""
                DELETE FROM sets 
                WHERE session_id IN (
                    SELECT id FROM sessions WHERE log_time < ?
                )
            """, (cutoff_date,))
            
            # 3. Delete the parent records (sessions)
            cursor.execute("DELETE FROM sessions WHERE log_time < ?", (cutoff_date,))

            conn.commit()
            
            # 200 OK is the standard success code for a deletion/modification
            return jsonify({"success": True, "message": "Database cleaned successfully"}), 200 
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def dashboard():
    conn = get_db()
    c = conn.cursor()
    
    # Current Month Stats
    today = c.execute("SELECT SUM(total_reps) FROM sessions WHERE date(log_time) = date('now')").fetchone()[0] or 0
    this_week = c.execute("SELECT SUM(total_reps) FROM sessions WHERE strftime('%Y-%W', log_time) = strftime('%Y-%W', 'now')").fetchone()[0] or 0
    this_month = c.execute("SELECT SUM(total_reps) FROM sessions WHERE strftime('%Y-%m', log_time) = strftime('%Y-%m', 'now')").fetchone()[0] or 0
    
    # All-Time Records
    max_day_row = c.execute("SELECT SUM(total_reps) as total FROM sessions GROUP BY date(log_time) ORDER BY total DESC LIMIT 1").fetchone()
    max_day = max_day_row[0] if max_day_row else 0

    max_week_row = c.execute("SELECT SUM(total_reps) as total FROM sessions GROUP BY strftime('%Y-%W', log_time) ORDER BY total DESC LIMIT 1").fetchone()
    max_week = max_week_row[0] if max_week_row else 0

    max_month_row = c.execute("SELECT SUM(total_reps) as total FROM sessions GROUP BY strftime('%Y-%m', log_time) ORDER BY total DESC LIMIT 1").fetchone()
    max_month = max_month_row[0] if max_month_row else 0

    max_set = c.execute("SELECT MAX(reps) FROM sets").fetchone()[0] or 0
    max_session = c.execute("SELECT MAX(total_reps) FROM sessions").fetchone()[0] or 0

    # Evaluate Goals
    goals_met = {
        "day": today >= 40,
        "week": this_week >= 224,
        "month": this_month >= 652
    }

    stats = {
        "today": today,
        "this_week": this_week,
        "this_month": this_month,
        "max_day": max_day,
        "max_week": max_week,
        "max_month": max_month,
        "max_set": max_set,
        "max_session": max_session,
    }

    # If the TV tower is the monthly goal, map progress to the monthly reps
    progress_percent = min((this_month / 652) * 100, 100)
    current_month_name = datetime.datetime.now().strftime("%B")

    return render_template('index.html', 
                           stats=stats, 
                           progress_percent=progress_percent,
                           current_month_name=current_month_name,
                           goals_met=goals_met)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True)