import sqlite3
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request

app = Flask(__name__, static_folder="public", static_url_path="/public")
DB_PATH = "pullups.sqlite"

# lets define our goals globally
goals = {"day": 40, "week": 224, "month": 652}


# proxy change
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Bootstrap the DB
with get_db() as conn:
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, total_reps INTEGER)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sets
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, reps INTEGER,
                     duration_seconds INTEGER, rest_time_after INTEGER, FOREIGN KEY(session_id) REFERENCES sessions(id))""")


@app.route("/api/add-entry", methods=["POST"])
def add_entry():
    data = request.json
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO sessions (total_reps) VALUES (?)", (data.get("total_reps", 0),)
        )
        session_id = cursor.lastrowid

        for s in data.get("sets", []):
            reps = int(s.get("reps", 0))
            if reps > 0:
                cursor.execute(
                    """INSERT INTO sets (session_id, reps, duration_seconds, rest_time_after)
                                  VALUES (?, ?, ?, ?)""",
                    (
                        session_id,
                        reps,
                        s.get("duration_seconds", 0),
                        s.get("rest_time_after", 0),
                    ),
                )

        conn.commit()
        return jsonify({"success": True, "id": session_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/clean-db", methods=["POST"])
def clean_db():
    try:
        # Using a context manager automatically helps manage connections
        with get_db() as conn:
            cursor = conn.cursor()

            # The exact cutoff date in standard SQLite format (YYYY-MM-DD HH:MM:SS)
            # Since London is on GMT in February, UTC matches your local time exactly.
            cutoff_date = "2026-02-22 19:30:00"

            # 1. Clean up any 0-rep sets
            cursor.execute("DELETE FROM sets WHERE reps = 0")

            # 2. Delete the child records (sets) for old sessions
            cursor.execute(
                """
                DELETE FROM sets
                WHERE session_id IN (
                    SELECT id FROM sessions WHERE log_time < ?
                )
            """,
                (cutoff_date,),
            )

            # 3. Delete the parent records (sessions)
            cursor.execute("DELETE FROM sessions WHERE log_time < ?", (cutoff_date,))

            conn.commit()

            # 200 OK is the standard success code for a deletion/modification
            return jsonify(
                {"success": True, "message": "Database cleaned successfully"}
            ), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def dashboard():
    conn = get_db()
    c = conn.cursor()

    # Current Month Stats
    today = (
        c.execute(
            "SELECT SUM(total_reps) FROM sessions WHERE date(log_time) = date('now')"
        ).fetchone()[0]
        or 0
    )
    this_week = (
        c.execute(
            "SELECT SUM(total_reps) FROM sessions WHERE strftime('%Y-%W', log_time) = strftime('%Y-%W', 'now')"
        ).fetchone()[0]
        or 0
    )
    this_month = (
        c.execute(
            "SELECT SUM(total_reps) FROM sessions WHERE strftime('%Y-%m', log_time) = strftime('%Y-%m', 'now')"
        ).fetchone()[0]
        or 0
    )

    # Current week punchcard
    # days = [
    #   {
    #       day_count,
    #       week_count_so_far,
    #       daily_achieved: day_count >= goals["day"],
    #       weekly_achieved: week_count_so_far >= goals["week"],
    #       monthly_achieved: month_count_so_far >= goals["month"],
    #   }
    #   ... same for other days
    # ]

    # init our days array with placeholders. This is done to make sure that we always have data for each
    days = [
        {
            "day_count": 0,
            "week_count_so_far": 0,
            "daily_achieved": False,
            "weekly_achieved": False,
            "monthly_achieved": False,
            "is_current": False,
        }
    ] * 7
    # we need to figure out which day of the current week we are working with.
    current_time = datetime.now()
    day = current_time.weekday()
    week_start_date = current_time - timedelta(days=day)
    week_start_date_string = week_start_date.strftime("%Y-%m-%d")
    month_start_date = week_start_date.strftime("%Y-%m") + "-1"

    # It is ridicuous that I need to go through this to run loop once on 0 index?
    # I guess maybe there is a more interesting way with a do while loop or something similar
    for i in range(day + 1):
        # Now we want to get all of the required information for the day and push it into the days array
        modified_time = current_time - timedelta(days=i)

        print(modified_time.strftime("%Y-%m-%d"))

        day_count = (
            c.execute(
                "SELECT SUM(total_reps) FROM sessions WHERE date(log_time) = ?",
                (modified_time.strftime("%Y-%m-%d"),),
            ).fetchone()[0]
            or 0
        )

        week_count_so_far = (
            c.execute(
                "SELECT SUM(total_reps) FROM sessions WHERE date(log_time) >= ? AND date(log_time) <= ?",
                (week_start_date_string, modified_time.strftime("%Y-%m-%d")),
            ).fetchone()[0]
            or 0
        )

        month_count_so_far = (
            c.execute(
                "SELECT SUM(total_reps) FROM sessions WHERE date(log_time) >= ? AND date(log_time) <= ?",
                (month_start_date, modified_time.strftime("%Y-%m-%d")),
            ).fetchone()[0]
            or 0
        )

        temp_day = {
            "day_count": day_count,
            "week_count_so_far": week_count_so_far,
            "daily_achieved": day_count >= goals["day"],
            "weekly_achieved": week_count_so_far >= goals["week"],
            "monthly_achieved": (
                month_count_so_far >= goals["month"]
                and month_count_so_far - day_count < goals["month"]
            ),
            "is_current": current_time.strftime("%Y-%m-%d")
            == modified_time.strftime("%Y-%m-%d"),
        }
        # Make sure to add item to the beginnig of the array, as we are moving back in time through the loop and remove last placeholder item
        days.insert(0, temp_day)
        days.pop()

    # All-Time Records
    max_day_row = c.execute(
        "SELECT SUM(total_reps) as total FROM sessions GROUP BY date(log_time) ORDER BY total DESC LIMIT 1"
    ).fetchone()
    max_day = max_day_row[0] if max_day_row else 0

    max_week_row = c.execute(
        "SELECT SUM(total_reps) as total FROM sessions GROUP BY strftime('%Y-%W', log_time) ORDER BY total DESC LIMIT 1"
    ).fetchone()
    max_week = max_week_row[0] if max_week_row else 0

    max_month_row = c.execute(
        "SELECT SUM(total_reps) as total FROM sessions GROUP BY strftime('%Y-%m', log_time) ORDER BY total DESC LIMIT 1"
    ).fetchone()
    max_month = max_month_row[0] if max_month_row else 0

    max_set = c.execute("SELECT MAX(reps) FROM sets").fetchone()[0] or 0
    max_session = c.execute("SELECT MAX(total_reps) FROM sessions").fetchone()[0] or 0

    # Evaluate Goals
    goals_met = {
        "day": today >= goals["day"],
        "week": this_week >= goals["week"],
        "month": this_month >= goals["month"],
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
    current_month_name = datetime.now().strftime("%B")

    return render_template(
        "index.html",
        stats=stats,
        progress_percent=progress_percent,
        current_month_name=current_month_name,
        goals_met=goals_met,
        days=days,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)
