import os
import sqlite3
import uuid
import string
import random
import io
import base64
from datetime import datetime, date
from functools import wraps

import qrcode
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, session
)
from werkzeug.security import generate_password_hash, check_password_hash

# ─── App Setup ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "showrunner-dev-secret-change-in-prod")
DATABASE = os.path.join(os.path.dirname(__file__), "showrunner.db")


# ─── Database ────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS organizers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            org_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            phone TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS venues (
            id TEXT PRIMARY KEY,
            organizer_id TEXT NOT NULL,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            rows INTEGER NOT NULL DEFAULT 5,
            seats_per_row INTEGER NOT NULL DEFAULT 8,
            capacity INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (organizer_id) REFERENCES organizers(id)
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            organizer_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            event_date TEXT NOT NULL,
            event_time TEXT NOT NULL,
            venue_id TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            FOREIGN KEY (organizer_id) REFERENCES organizers(id),
            FOREIGN KEY (venue_id) REFERENCES venues(id)
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            user_id TEXT,
            code TEXT NOT NULL UNIQUE,
            customer_name TEXT NOT NULL,
            customer_email TEXT,
            customer_phone TEXT NOT NULL,
            seats TEXT NOT NULL,
            total_amount REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'confirmed',
            verified INTEGER NOT NULL DEFAULT 0,
            verified_at TEXT,
            booked_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()


init_db()


# ─── Auth Decorators ─────────────────────────────────────────
def require_organizer(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("organizer_id"):
            flash("Please log in as an organizer.", "error")
            return redirect(url_for("org_login"))
        return f(*args, **kwargs)
    return decorated


# ─── Template Context ─────────────────────────────────────────
@app.context_processor
def inject_session_info():
    organizer_id = session.get("organizer_id")
    user_id = session.get("user_id")
    organizer = None
    user = None
    if organizer_id:
        conn = get_db()
        organizer = conn.execute(
            "SELECT * FROM organizers WHERE id = ?", (organizer_id,)
        ).fetchone()
        conn.close()
    if user_id:
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        conn.close()
    return {"current_organizer": organizer, "current_user": user}


# ─── Utility ─────────────────────────────────────────────────
def new_id():
    return uuid.uuid4().hex[:12]


def generate_ticket_code():
    chars = string.ascii_uppercase.replace("I", "").replace("O", "") + "23456789"
    parts = ["".join(random.choices(chars, k=4)) for _ in range(3)]
    return "-".join(parts)


def generate_qr_base64(data_str):
    qr = qrcode.QRCode(
        version=1, box_size=8, border=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def get_booked_seats(event_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT seats FROM bookings WHERE event_id = ?", (event_id,)
    ).fetchall()
    conn.close()
    all_seats = []
    for r in rows:
        all_seats.extend(r["seats"].split(","))
    return [s.strip() for s in all_seats if s.strip()]


def format_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%a, %b %d %Y")
    except Exception:
        return d


def format_time(t):
    try:
        return datetime.strptime(t, "%H:%M").strftime("%I:%M %p")
    except Exception:
        return t


app.jinja_env.filters["fmtdate"] = format_date
app.jinja_env.filters["fmttime"] = format_time


# ═══════════════════════════════════════════════════════════════
# ORGANIZER AUTH
# ═══════════════════════════════════════════════════════════════

@app.route("/org/register", methods=["GET", "POST"])
def org_register():
    if session.get("organizer_id"):
        return redirect(url_for("org_dashboard"))

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        org_name = request.form["org_name"].strip()
        password = request.form["password"]

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("org_register.html")

        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM organizers WHERE email = ?", (email,)
        ).fetchone()
        if existing:
            conn.close()
            flash("An account with this email already exists.", "error")
            return render_template("org_register.html")

        conn.execute(
            """INSERT INTO organizers (id, name, email, password_hash, org_name, created_at)
               VALUES (?,?,?,?,?,?)""",
            (new_id(), name, email, generate_password_hash(password), org_name,
             datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        flash("Account created! Please log in.", "success")
        return redirect(url_for("org_login"))

    return render_template("org_register.html")


@app.route("/org/login", methods=["GET", "POST"])
def org_login():
    if session.get("organizer_id"):
        return redirect(url_for("org_dashboard"))

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        org = conn.execute(
            "SELECT * FROM organizers WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        if org and check_password_hash(org["password_hash"], password):
            session.clear()
            session["organizer_id"] = org["id"]
            session["role"] = "organizer"
            return redirect(url_for("org_dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("org_login.html")


@app.route("/org/logout")
def org_logout():
    session.clear()
    return redirect(url_for("org_login"))


# ═══════════════════════════════════════════════════════════════
# ORGANIZER DASHBOARD
# ═══════════════════════════════════════════════════════════════

@app.route("/org")
@app.route("/org/dashboard")
@require_organizer
def org_dashboard():
    org_id = session["organizer_id"]
    conn = get_db()

    total_events = conn.execute(
        "SELECT COUNT(*) FROM events WHERE organizer_id = ?", (org_id,)
    ).fetchone()[0]

    upcoming = conn.execute(
        "SELECT COUNT(*) FROM events WHERE organizer_id = ? AND event_date >= ?",
        (org_id, date.today().isoformat()),
    ).fetchone()[0]

    total_bookings = conn.execute("""
        SELECT COUNT(*) FROM bookings b
        JOIN events e ON b.event_id = e.id
        WHERE e.organizer_id = ?
    """, (org_id,)).fetchone()[0]

    verified = conn.execute("""
        SELECT COUNT(*) FROM bookings b
        JOIN events e ON b.event_id = e.id
        WHERE e.organizer_id = ? AND b.verified = 1
    """, (org_id,)).fetchone()[0]

    revenue_rows = conn.execute("""
        SELECT b.total_amount FROM bookings b
        JOIN events e ON b.event_id = e.id
        WHERE e.organizer_id = ?
    """, (org_id,)).fetchall()
    total_revenue = sum(r["total_amount"] for r in revenue_rows)

    recent_bookings = conn.execute("""
        SELECT b.*, e.title as event_title
        FROM bookings b
        JOIN events e ON b.event_id = e.id
        WHERE e.organizer_id = ?
        ORDER BY b.booked_at DESC LIMIT 8
    """, (org_id,)).fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        stats={
            "total_events": total_events,
            "upcoming": upcoming,
            "total_bookings": total_bookings,
            "verified": verified,
            "total_revenue": f"{total_revenue:,.0f}",
        },
        recent_bookings=recent_bookings,
    )


# ═══════════════════════════════════════════════════════════════
# ORGANIZER — EVENTS
# ═══════════════════════════════════════════════════════════════

@app.route("/org/events")
@require_organizer
def org_events_list():
    org_id = session["organizer_id"]
    conn = get_db()
    events = conn.execute("""
        SELECT e.*, v.name as venue_name, v.capacity
        FROM events e
        LEFT JOIN venues v ON e.venue_id = v.id
        WHERE e.organizer_id = ?
        ORDER BY e.event_date DESC
    """, (org_id,)).fetchall()
    conn.close()

    events_data = []
    for ev in events:
        booked = len(get_booked_seats(ev["id"]))
        events_data.append({**dict(ev), "booked": booked})

    return render_template("events.html", events=events_data)


@app.route("/org/events/create", methods=["GET", "POST"])
@require_organizer
def org_create_event():
    org_id = session["organizer_id"]
    conn = get_db()
    venues = conn.execute(
        "SELECT * FROM venues WHERE organizer_id = ? ORDER BY name", (org_id,)
    ).fetchall()

    if request.method == "POST":
        eid = new_id()
        conn.execute(
            """INSERT INTO events (id, organizer_id, title, description, event_date,
               event_time, venue_id, price, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                eid, org_id,
                request.form["title"],
                request.form.get("description", ""),
                request.form["event_date"],
                request.form["event_time"],
                request.form["venue_id"],
                float(request.form["price"]),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        flash("Event created successfully!", "success")
        return redirect(url_for("org_events_list"))

    conn.close()
    return render_template("create_event.html", venues=venues)


@app.route("/org/events/<event_id>")
@require_organizer
def org_event_detail(event_id):
    org_id = session["organizer_id"]
    conn = get_db()
    event = conn.execute("""
        SELECT e.*, v.name as venue_name, v.location as venue_location,
               v.rows, v.seats_per_row, v.capacity
        FROM events e LEFT JOIN venues v ON e.venue_id = v.id
        WHERE e.id = ? AND e.organizer_id = ?
    """, (event_id, org_id)).fetchone()

    if not event:
        conn.close()
        flash("Event not found.", "error")
        return redirect(url_for("org_events_list"))

    bookings = conn.execute(
        "SELECT * FROM bookings WHERE event_id = ? ORDER BY booked_at DESC",
        (event_id,),
    ).fetchall()
    conn.close()

    booked_seats = get_booked_seats(event_id)
    return render_template(
        "event_detail.html", event=event, bookings=bookings, booked_seats=booked_seats
    )


@app.route("/org/events/<event_id>/delete", methods=["POST"])
@require_organizer
def org_delete_event(event_id):
    org_id = session["organizer_id"]
    conn = get_db()
    event = conn.execute(
        "SELECT id FROM events WHERE id = ? AND organizer_id = ?", (event_id, org_id)
    ).fetchone()
    if event:
        conn.execute("DELETE FROM bookings WHERE event_id = ?", (event_id,))
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
        flash("Event deleted.", "success")
    conn.close()
    return redirect(url_for("org_events_list"))


# ═══════════════════════════════════════════════════════════════
# ORGANIZER — VENUES
# ═══════════════════════════════════════════════════════════════

@app.route("/org/venues")
@require_organizer
def org_venues_list():
    org_id = session["organizer_id"]
    conn = get_db()
    venues = conn.execute(
        "SELECT * FROM venues WHERE organizer_id = ? ORDER BY name", (org_id,)
    ).fetchall()
    conn.close()
    return render_template("venues.html", venues=venues)


@app.route("/org/venues/create", methods=["GET", "POST"])
@require_organizer
def org_create_venue():
    org_id = session["organizer_id"]
    if request.method == "POST":
        rows = int(request.form["rows"])
        seats_per_row = int(request.form["seats_per_row"])
        conn = get_db()
        conn.execute(
            """INSERT INTO venues (id, organizer_id, name, location, rows,
               seats_per_row, capacity, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (
                new_id(), org_id,
                request.form["name"],
                request.form["location"],
                rows,
                seats_per_row,
                rows * seats_per_row,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        flash("Venue added!", "success")
        return redirect(url_for("org_venues_list"))

    return render_template("create_venue.html")


@app.route("/org/venues/<venue_id>/delete", methods=["POST"])
@require_organizer
def org_delete_venue(venue_id):
    org_id = session["organizer_id"]
    conn = get_db()
    conn.execute(
        "DELETE FROM venues WHERE id = ? AND organizer_id = ?", (venue_id, org_id)
    )
    conn.commit()
    conn.close()
    flash("Venue deleted.", "success")
    return redirect(url_for("org_venues_list"))


# ═══════════════════════════════════════════════════════════════
# ORGANIZER — BOOKINGS
# ═══════════════════════════════════════════════════════════════

@app.route("/org/bookings")
@require_organizer
def org_bookings_list():
    org_id = session["organizer_id"]
    conn = get_db()
    bookings = conn.execute("""
        SELECT b.*, e.title as event_title, e.event_date, e.event_time
        FROM bookings b
        JOIN events e ON b.event_id = e.id
        WHERE e.organizer_id = ?
        ORDER BY b.booked_at DESC
    """, (org_id,)).fetchall()
    conn.close()
    return render_template("bookings.html", bookings=bookings)


# ═══════════════════════════════════════════════════════════════
# ORGANIZER — VERIFY (tenant-scoped: only verifies own events)
# ═══════════════════════════════════════════════════════════════

@app.route("/org/verify", methods=["GET", "POST"])
@require_organizer
def org_verify_ticket():
    org_id = session["organizer_id"]
    result = None
    code_input = ""

    if request.method == "POST":
        code_input = request.form.get("code", "").strip().upper().replace(" ", "")
        clean = code_input.replace("-", "")

        conn = get_db()
        booking = conn.execute("""
            SELECT b.*, e.title as event_title, e.event_date, e.event_time,
                   v.name as venue_name
            FROM bookings b
            JOIN events e ON b.event_id = e.id
            LEFT JOIN venues v ON e.venue_id = v.id
            WHERE REPLACE(b.code, '-', '') = ?
              AND e.organizer_id = ?
        """, (clean, org_id)).fetchone()

        if booking:
            already = booking["verified"] == 1
            if not already:
                conn.execute(
                    "UPDATE bookings SET verified = 1, verified_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), booking["id"]),
                )
                conn.commit()
            result = {
                "status": "already" if already else "success",
                "booking": dict(booking),
            }
        else:
            result = {"status": "invalid"}
        conn.close()

    return render_template("verify.html", result=result, code_input=code_input)


# ═══════════════════════════════════════════════════════════════
# USER AUTH
# ═══════════════════════════════════════════════════════════════

@app.route("/register", methods=["GET", "POST"])
def user_register():
    if session.get("user_id"):
        return redirect(url_for("book_list"))

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form["password"]

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("user_register.html")

        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        if existing:
            conn.close()
            flash("An account with this email already exists.", "error")
            return render_template("user_register.html")

        conn.execute(
            """INSERT INTO users (id, name, email, password_hash, phone, created_at)
               VALUES (?,?,?,?,?,?)""",
            (new_id(), name, email, generate_password_hash(password), phone,
             datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        flash("Account created! Please log in.", "success")
        return redirect(url_for("user_login"))

    return render_template("user_register.html")


@app.route("/login", methods=["GET", "POST"])
def user_login():
    if session.get("user_id"):
        return redirect(url_for("book_list"))

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["role"] = "user"
            return redirect(url_for("book_list"))

        flash("Invalid email or password.", "error")

    return render_template("user_login.html")


@app.route("/logout")
def user_logout():
    session.clear()
    return redirect(url_for("book_list"))


# ═══════════════════════════════════════════════════════════════
# PUBLIC — BROWSE & BOOK
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if session.get("organizer_id"):
        return redirect(url_for("org_dashboard"))
    return redirect(url_for("book_list"))


@app.route("/events")
def book_list():
    conn = get_db()
    events = conn.execute("""
        SELECT e.*, v.name as venue_name, v.capacity, o.org_name as organizer_name
        FROM events e
        LEFT JOIN venues v ON e.venue_id = v.id
        LEFT JOIN organizers o ON e.organizer_id = o.id
        WHERE e.event_date >= ? AND e.status = 'active'
        ORDER BY e.event_date ASC
    """, (date.today().isoformat(),)).fetchall()
    conn.close()

    events_data = []
    for ev in events:
        booked = len(get_booked_seats(ev["id"]))
        events_data.append({**dict(ev), "booked": booked})

    return render_template("book.html", events=events_data)


@app.route("/book/<event_id>", methods=["GET", "POST"])
def book_event(event_id):
    conn = get_db()
    event = conn.execute("""
        SELECT e.*, v.name as venue_name, v.location as venue_location,
               v.rows, v.seats_per_row, v.capacity, o.org_name as organizer_name
        FROM events e
        LEFT JOIN venues v ON e.venue_id = v.id
        LEFT JOIN organizers o ON e.organizer_id = o.id
        WHERE e.id = ? AND e.status = 'active'
    """, (event_id,)).fetchone()

    if not event:
        conn.close()
        flash("Event not found.", "error")
        return redirect(url_for("book_list"))

    booked_seats = get_booked_seats(event_id)

    if request.method == "POST":
        seats_str = request.form.get("selected_seats", "")
        seats = [s.strip() for s in seats_str.split(",") if s.strip()]

        if not seats:
            flash("Please select at least one seat.", "error")
            conn.close()
            return redirect(url_for("book_event", event_id=event_id))

        for s in seats:
            if s in booked_seats:
                flash(f"Seat {s} was just taken. Please reselect.", "error")
                conn.close()
                return redirect(url_for("book_event", event_id=event_id))

        code = generate_ticket_code()
        total = event["price"] * len(seats)
        booking_id = new_id()
        user_id = session.get("user_id")

        conn.execute(
            """INSERT INTO bookings (id, event_id, user_id, code, customer_name,
               customer_email, customer_phone, seats, total_amount, booked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                booking_id, event_id, user_id, code,
                request.form["customer_name"],
                request.form.get("customer_email", ""),
                request.form["customer_phone"],
                ", ".join(seats),
                total,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        flash("Booking confirmed!", "success")
        return redirect(url_for("view_ticket", booking_id=booking_id))

    conn.close()
    return render_template("book_event.html", event=event, booked_seats=booked_seats)


@app.route("/ticket/<booking_id>")
def view_ticket(booking_id):
    conn = get_db()
    booking = conn.execute(
        "SELECT * FROM bookings WHERE id = ?", (booking_id,)
    ).fetchone()
    if not booking:
        conn.close()
        flash("Booking not found.", "error")
        return redirect(url_for("book_list"))

    event = conn.execute("""
        SELECT e.*, v.name as venue_name, v.location as venue_location,
               o.org_name as organizer_name
        FROM events e
        LEFT JOIN venues v ON e.venue_id = v.id
        LEFT JOIN organizers o ON e.organizer_id = o.id
        WHERE e.id = ?
    """, (booking["event_id"],)).fetchone()
    conn.close()

    qr_data = f"SHOWRUNNER|{booking['code']}|{booking['customer_name']}|{booking['seats']}"
    qr_b64 = generate_qr_base64(qr_data)

    return render_template("ticket.html", booking=booking, event=event, qr_base64=qr_b64)


# ─── API ─────────────────────────────────────────────────────
@app.route("/api/booked-seats/<event_id>")
def api_booked_seats(event_id):
    return jsonify(get_booked_seats(event_id))


# ─── Run ─────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
