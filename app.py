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
from werkzeug.utils import secure_filename

# ─── App Setup ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "showrunner-dev-secret-change-in-prod")
DATABASE      = os.path.join(os.path.dirname(__file__), "showrunner.db")
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


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
            rows INTEGER NOT NULL,
            seats_per_row INTEGER NOT NULL,
            capacity INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (organizer_id) REFERENCES organizers(id)
        );

        CREATE TABLE IF NOT EXISTS venue_photos (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            caption TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (venue_id) REFERENCES venues(id)
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

        CREATE TABLE IF NOT EXISTS seat_tiers (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            color TEXT NOT NULL DEFAULT '#f5c842',
            row_from TEXT NOT NULL,
            row_to TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id)
        );

        CREATE TABLE IF NOT EXISTS performers (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT,
            bio TEXT,
            photo TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id)
        );

        CREATE TABLE IF NOT EXISTS event_photos (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            caption TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id)
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

for sub in ("venues", "events", "performers"):
    os.makedirs(os.path.join(UPLOAD_FOLDER, sub), exist_ok=True)


# ─── Auth Decorators ─────────────────────────────────────────
def require_organizer(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("organizer_id"):
            flash("Please log in as an organizer.", "error")
            return redirect(url_for("org_login"))
        return f(*args, **kwargs)
    return decorated


def require_user(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to view your tickets.", "error")
            return redirect(url_for("user_login"))
        return f(*args, **kwargs)
    return decorated


# ─── Template Context ─────────────────────────────────────────
@app.context_processor
def inject_session_info():
    organizer_id = session.get("organizer_id")
    user_id      = session.get("user_id")
    organizer    = None
    user         = None
    if organizer_id:
        conn = get_db()
        organizer = conn.execute("SELECT * FROM organizers WHERE id = ?", (organizer_id,)).fetchone()
        conn.close()
    if user_id:
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
    return {"current_organizer": organizer, "current_user": user}


# ─── Utility ─────────────────────────────────────────────────
LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def new_id():
    return uuid.uuid4().hex[:12]


def generate_ticket_code():
    chars = string.ascii_uppercase.replace("I", "").replace("O", "") + "23456789"
    return "-".join("".join(random.choices(chars, k=4)) for _ in range(3))


def generate_qr_base64(data_str):
    qr = qrcode.QRCode(version=1, box_size=8, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def get_booked_seats(event_id):
    conn = get_db()
    rows = conn.execute("SELECT seats FROM bookings WHERE event_id = ?", (event_id,)).fetchall()
    conn.close()
    all_seats = []
    for r in rows:
        all_seats.extend(r["seats"].split(","))
    return [s.strip() for s in all_seats if s.strip()]


def calc_seat_total(seats, tiers, base_price):
    """Return (total, breakdown_list). breakdown = [{name, price, count, color}]"""
    if not tiers:
        return base_price * len(seats), []

    breakdown = {}
    total = 0
    for seat in seats:
        row_label = seat[0].upper()
        row_idx   = LABELS.index(row_label) if row_label in LABELS else 0
        tier_match = None
        for t in tiers:
            fi = LABELS.index(t["row_from"]) if t["row_from"] in LABELS else 0
            ti = LABELS.index(t["row_to"])   if t["row_to"]   in LABELS else 0
            if fi <= row_idx <= ti:
                tier_match = t
                break
        if tier_match:
            price = tier_match["price"]
            key   = tier_match["id"]
            if key not in breakdown:
                breakdown[key] = {"name": tier_match["name"], "price": price,
                                  "color": tier_match["color"], "count": 0}
            breakdown[key]["count"] += 1
        else:
            price = base_price
            if "_base" not in breakdown:
                breakdown["_base"] = {"name": "Standard", "price": base_price,
                                      "color": "#8888aa", "count": 0}
            breakdown["_base"]["count"] += 1
        total += price

    return total, list(breakdown.values())


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file, subfolder):
    if not file or not file.filename or not allowed_file(file.filename):
        return None
    ext      = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex[:16]}.{ext}"
    folder   = os.path.join(UPLOAD_FOLDER, subfolder)
    os.makedirs(folder, exist_ok=True)
    file.save(os.path.join(folder, filename))
    return f"uploads/{subfolder}/{filename}"


def delete_upload(relative_path):
    if relative_path:
        full = os.path.join(os.path.dirname(__file__), "static", relative_path)
        if os.path.exists(full):
            os.remove(full)


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
        name     = request.form["name"].strip()
        email    = request.form["email"].strip().lower()
        org_name = request.form["org_name"].strip()
        password = request.form["password"]
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("org_register.html")
        conn = get_db()
        if conn.execute("SELECT id FROM organizers WHERE email=?", (email,)).fetchone():
            conn.close()
            flash("An account with this email already exists.", "error")
            return render_template("org_register.html")
        conn.execute(
            "INSERT INTO organizers (id,name,email,password_hash,org_name,created_at) VALUES(?,?,?,?,?,?)",
            (new_id(), name, email, generate_password_hash(password), org_name, datetime.now().isoformat()))
        conn.commit(); conn.close()
        flash("Account created! Please log in.", "success")
        return redirect(url_for("org_login"))
    return render_template("org_register.html")


@app.route("/org/login", methods=["GET", "POST"])
def org_login():
    if session.get("organizer_id"):
        return redirect(url_for("org_dashboard"))
    if request.method == "POST":
        email    = request.form["email"].strip().lower()
        password = request.form["password"]
        conn = get_db()
        org  = conn.execute("SELECT * FROM organizers WHERE email=?", (email,)).fetchone()
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
    conn   = get_db()
    total_events   = conn.execute("SELECT COUNT(*) FROM events WHERE organizer_id=?", (org_id,)).fetchone()[0]
    upcoming       = conn.execute("SELECT COUNT(*) FROM events WHERE organizer_id=? AND event_date>=?", (org_id, date.today().isoformat())).fetchone()[0]
    total_bookings = conn.execute("SELECT COUNT(*) FROM bookings b JOIN events e ON b.event_id=e.id WHERE e.organizer_id=?", (org_id,)).fetchone()[0]
    verified       = conn.execute("SELECT COUNT(*) FROM bookings b JOIN events e ON b.event_id=e.id WHERE e.organizer_id=? AND b.verified=1", (org_id,)).fetchone()[0]
    revenue_rows   = conn.execute("SELECT b.total_amount FROM bookings b JOIN events e ON b.event_id=e.id WHERE e.organizer_id=?", (org_id,)).fetchall()
    total_revenue  = sum(r["total_amount"] for r in revenue_rows)
    recent_bookings = conn.execute("""
        SELECT b.*, e.title as event_title FROM bookings b
        JOIN events e ON b.event_id=e.id WHERE e.organizer_id=?
        ORDER BY b.booked_at DESC LIMIT 8
    """, (org_id,)).fetchall()
    conn.close()
    return render_template("dashboard.html", stats={
        "total_events": total_events, "upcoming": upcoming,
        "total_bookings": total_bookings, "verified": verified,
        "total_revenue": f"{total_revenue:,.0f}",
    }, recent_bookings=recent_bookings)


# ═══════════════════════════════════════════════════════════════
# ORGANIZER — EVENTS
# ═══════════════════════════════════════════════════════════════

@app.route("/org/events")
@require_organizer
def org_events_list():
    org_id = session["organizer_id"]
    conn   = get_db()
    events = conn.execute("""
        SELECT e.*, v.name as venue_name, v.capacity FROM events e
        LEFT JOIN venues v ON e.venue_id=v.id
        WHERE e.organizer_id=? ORDER BY e.event_date DESC
    """, (org_id,)).fetchall()
    conn.close()
    events_data = [{**dict(ev), "booked": len(get_booked_seats(ev["id"]))} for ev in events]
    return render_template("events.html", events=events_data)


@app.route("/org/events/create", methods=["GET", "POST"])
@require_organizer
def org_create_event():
    org_id = session["organizer_id"]
    conn   = get_db()
    venues = conn.execute("SELECT * FROM venues WHERE organizer_id=? ORDER BY name", (org_id,)).fetchall()
    if request.method == "POST":
        eid = new_id()
        conn.execute(
            "INSERT INTO events (id,organizer_id,title,description,event_date,event_time,venue_id,price,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (eid, org_id, request.form["title"], request.form.get("description",""),
             request.form["event_date"], request.form["event_time"],
             request.form["venue_id"], float(request.form["price"]),
             datetime.now().isoformat()))
        conn.commit(); conn.close()
        flash("Event created! Add performers, photos and ticket tiers.", "success")
        return redirect(url_for("org_event_detail", event_id=eid))
    conn.close()
    return render_template("create_event.html", venues=venues)


@app.route("/org/events/<event_id>")
@require_organizer
def org_event_detail(event_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    event  = conn.execute("""
        SELECT e.*, v.name as venue_name, v.location as venue_location,
               v.rows, v.seats_per_row, v.capacity
        FROM events e LEFT JOIN venues v ON e.venue_id=v.id
        WHERE e.id=? AND e.organizer_id=?
    """, (event_id, org_id)).fetchone()
    if not event:
        conn.close(); flash("Event not found.", "error")
        return redirect(url_for("org_events_list"))
    bookings   = conn.execute("SELECT * FROM bookings WHERE event_id=? ORDER BY booked_at DESC", (event_id,)).fetchall()
    performers = conn.execute("SELECT * FROM performers WHERE event_id=? ORDER BY created_at", (event_id,)).fetchall()
    photos     = conn.execute("SELECT * FROM event_photos WHERE event_id=? ORDER BY created_at DESC", (event_id,)).fetchall()
    tiers      = [dict(r) for r in conn.execute("SELECT * FROM seat_tiers WHERE event_id=? ORDER BY row_from", (event_id,)).fetchall()]
    conn.close()
    booked_seats = get_booked_seats(event_id)
    row_letters  = list(LABELS[:event["rows"]]) if event["rows"] else []
    return render_template("event_detail.html", event=event, bookings=bookings,
                           booked_seats=booked_seats, performers=performers,
                           photos=photos, tiers=tiers, row_letters=row_letters)


@app.route("/org/events/<event_id>/delete", methods=["POST"])
@require_organizer
def org_delete_event(event_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    if conn.execute("SELECT id FROM events WHERE id=? AND organizer_id=?", (event_id, org_id)).fetchone():
        for r in conn.execute("SELECT filename FROM event_photos WHERE event_id=?", (event_id,)).fetchall():
            delete_upload(r["filename"])
        for r in conn.execute("SELECT photo FROM performers WHERE event_id=? AND photo IS NOT NULL", (event_id,)).fetchall():
            delete_upload(r["photo"])
        conn.execute("DELETE FROM bookings    WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM performers  WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM event_photos WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM seat_tiers  WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM events      WHERE id=?",        (event_id,))
        conn.commit(); flash("Event deleted.", "success")
    conn.close()
    return redirect(url_for("org_events_list"))


# ─── Seat Tiers ──────────────────────────────────────────────

@app.route("/org/events/<event_id>/tiers/add", methods=["POST"])
@require_organizer
def org_add_tier(event_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    event  = conn.execute("SELECT id,price FROM events WHERE id=? AND organizer_id=?", (event_id, org_id)).fetchone()
    if not event:
        conn.close(); flash("Event not found.", "error")
        return redirect(url_for("org_events_list"))
    name     = request.form["name"].strip()
    price    = float(request.form["price"])
    color    = request.form.get("color", "#f5c842").strip()
    row_from = request.form["row_from"].upper()
    row_to   = request.form["row_to"].upper()
    if LABELS.index(row_from) > LABELS.index(row_to):
        row_from, row_to = row_to, row_from
    conn.execute(
        "INSERT INTO seat_tiers (id,event_id,name,price,color,row_from,row_to,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (new_id(), event_id, name, price, color, row_from, row_to, datetime.now().isoformat()))
    conn.commit(); conn.close()
    flash(f"Tier '{name}' added!", "success")
    return redirect(url_for("org_event_detail", event_id=event_id))


@app.route("/org/events/<event_id>/tiers/<tier_id>/delete", methods=["POST"])
@require_organizer
def org_delete_tier(event_id, tier_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    conn.execute("""
        DELETE FROM seat_tiers WHERE id=?
        AND event_id IN (SELECT id FROM events WHERE id=? AND organizer_id=?)
    """, (tier_id, event_id, org_id))
    conn.commit(); conn.close()
    return redirect(url_for("org_event_detail", event_id=event_id))


# ─── Performers ───────────────────────────────────────────────

@app.route("/org/events/<event_id>/performers/add", methods=["POST"])
@require_organizer
def org_add_performer(event_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    if not conn.execute("SELECT id FROM events WHERE id=? AND organizer_id=?", (event_id, org_id)).fetchone():
        conn.close(); flash("Event not found.", "error")
        return redirect(url_for("org_events_list"))
    photo = save_upload(request.files.get("photo"), "performers")
    conn.execute(
        "INSERT INTO performers (id,event_id,name,role,bio,photo,created_at) VALUES(?,?,?,?,?,?,?)",
        (new_id(), event_id, request.form["name"].strip(),
         request.form.get("role","").strip(), request.form.get("bio","").strip(),
         photo, datetime.now().isoformat()))
    conn.commit(); conn.close()
    flash("Performer added!", "success")
    return redirect(url_for("org_event_detail", event_id=event_id))


@app.route("/org/events/<event_id>/performers/<performer_id>/delete", methods=["POST"])
@require_organizer
def org_delete_performer(event_id, performer_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    row    = conn.execute("""
        SELECT p.* FROM performers p JOIN events e ON p.event_id=e.id
        WHERE p.id=? AND e.organizer_id=?
    """, (performer_id, org_id)).fetchone()
    if row:
        delete_upload(row["photo"])
        conn.execute("DELETE FROM performers WHERE id=?", (performer_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("org_event_detail", event_id=event_id))


# ─── Event Gallery ────────────────────────────────────────────

@app.route("/org/events/<event_id>/photos/add", methods=["POST"])
@require_organizer
def org_add_event_photo(event_id):
    org_id   = session["organizer_id"]
    conn     = get_db()
    if not conn.execute("SELECT id FROM events WHERE id=? AND organizer_id=?", (event_id, org_id)).fetchone():
        conn.close(); flash("Event not found.", "error")
        return redirect(url_for("org_events_list"))
    filename = save_upload(request.files.get("photo"), "events")
    if not filename:
        conn.close(); flash("Invalid file. Use PNG, JPG, GIF or WEBP.", "error")
        return redirect(url_for("org_event_detail", event_id=event_id))
    conn.execute(
        "INSERT INTO event_photos (id,event_id,filename,caption,created_at) VALUES(?,?,?,?,?)",
        (new_id(), event_id, filename, request.form.get("caption","").strip(), datetime.now().isoformat()))
    conn.commit(); conn.close()
    flash("Photo added!", "success")
    return redirect(url_for("org_event_detail", event_id=event_id))


@app.route("/org/events/<event_id>/photos/<photo_id>/delete", methods=["POST"])
@require_organizer
def org_delete_event_photo(event_id, photo_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    row    = conn.execute("""
        SELECT ep.* FROM event_photos ep JOIN events e ON ep.event_id=e.id
        WHERE ep.id=? AND e.organizer_id=?
    """, (photo_id, org_id)).fetchone()
    if row:
        delete_upload(row["filename"])
        conn.execute("DELETE FROM event_photos WHERE id=?", (photo_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("org_event_detail", event_id=event_id))


# ═══════════════════════════════════════════════════════════════
# ORGANIZER — VENUES
# ═══════════════════════════════════════════════════════════════

@app.route("/org/venues")
@require_organizer
def org_venues_list():
    org_id = session["organizer_id"]
    conn   = get_db()
    venues = conn.execute("SELECT * FROM venues WHERE organizer_id=? ORDER BY name", (org_id,)).fetchall()
    conn.close()
    return render_template("venues.html", venues=venues)


@app.route("/org/venues/create", methods=["GET", "POST"])
@require_organizer
def org_create_venue():
    org_id = session["organizer_id"]
    if request.method == "POST":
        rows          = int(request.form["rows"])
        seats_per_row = int(request.form["seats_per_row"])
        conn = get_db()
        vid  = new_id()
        conn.execute(
            "INSERT INTO venues (id,organizer_id,name,location,rows,seats_per_row,capacity,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (vid, org_id, request.form["name"], request.form["location"],
             rows, seats_per_row, rows * seats_per_row, datetime.now().isoformat()))
        conn.commit(); conn.close()
        flash("Venue created! Add some photos to show it off.", "success")
        return redirect(url_for("org_venue_detail", venue_id=vid))
    return render_template("create_venue.html")


@app.route("/org/venues/<venue_id>")
@require_organizer
def org_venue_detail(venue_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    venue  = conn.execute("SELECT * FROM venues WHERE id=? AND organizer_id=?", (venue_id, org_id)).fetchone()
    if not venue:
        conn.close(); flash("Venue not found.", "error")
        return redirect(url_for("org_venues_list"))
    photos = conn.execute("SELECT * FROM venue_photos WHERE venue_id=? ORDER BY created_at DESC", (venue_id,)).fetchall()
    conn.close()
    return render_template("venue_detail.html", venue=venue, photos=photos)


@app.route("/org/venues/<venue_id>/photos/add", methods=["POST"])
@require_organizer
def org_add_venue_photo(venue_id):
    org_id   = session["organizer_id"]
    conn     = get_db()
    if not conn.execute("SELECT id FROM venues WHERE id=? AND organizer_id=?", (venue_id, org_id)).fetchone():
        conn.close(); flash("Venue not found.", "error")
        return redirect(url_for("org_venues_list"))
    filename = save_upload(request.files.get("photo"), "venues")
    if not filename:
        conn.close(); flash("Invalid file. Use PNG, JPG, GIF or WEBP.", "error")
        return redirect(url_for("org_venue_detail", venue_id=venue_id))
    conn.execute(
        "INSERT INTO venue_photos (id,venue_id,filename,caption,created_at) VALUES(?,?,?,?,?)",
        (new_id(), venue_id, filename, request.form.get("caption","").strip(), datetime.now().isoformat()))
    conn.commit(); conn.close()
    flash("Photo added!", "success")
    return redirect(url_for("org_venue_detail", venue_id=venue_id))


@app.route("/org/venues/<venue_id>/photos/<photo_id>/delete", methods=["POST"])
@require_organizer
def org_delete_venue_photo(venue_id, photo_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    row    = conn.execute("""
        SELECT vp.* FROM venue_photos vp JOIN venues v ON vp.venue_id=v.id
        WHERE vp.id=? AND v.organizer_id=?
    """, (photo_id, org_id)).fetchone()
    if row:
        delete_upload(row["filename"])
        conn.execute("DELETE FROM venue_photos WHERE id=?", (photo_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("org_venue_detail", venue_id=venue_id))


@app.route("/org/venues/<venue_id>/delete", methods=["POST"])
@require_organizer
def org_delete_venue(venue_id):
    org_id = session["organizer_id"]
    conn   = get_db()
    for r in conn.execute("SELECT filename FROM venue_photos WHERE venue_id=?", (venue_id,)).fetchall():
        delete_upload(r["filename"])
    conn.execute("DELETE FROM venue_photos WHERE venue_id=?", (venue_id,))
    conn.execute("DELETE FROM venues WHERE id=? AND organizer_id=?", (venue_id, org_id))
    conn.commit(); conn.close()
    flash("Venue deleted.", "success")
    return redirect(url_for("org_venues_list"))


# ═══════════════════════════════════════════════════════════════
# ORGANIZER — BOOKINGS & VERIFY
# ═══════════════════════════════════════════════════════════════

@app.route("/org/bookings")
@require_organizer
def org_bookings_list():
    org_id = session["organizer_id"]
    conn   = get_db()
    bookings = conn.execute("""
        SELECT b.*, e.title as event_title, e.event_date, e.event_time FROM bookings b
        JOIN events e ON b.event_id=e.id WHERE e.organizer_id=? ORDER BY b.booked_at DESC
    """, (org_id,)).fetchall()
    conn.close()
    return render_template("bookings.html", bookings=bookings)


@app.route("/org/verify", methods=["GET", "POST"])
@require_organizer
def org_verify_ticket():
    org_id = session["organizer_id"]
    result = None; code_input = ""
    if request.method == "POST":
        code_input = request.form.get("code","").strip().upper().replace(" ","")
        clean      = code_input.replace("-","")
        conn       = get_db()
        booking    = conn.execute("""
            SELECT b.*, e.title as event_title, e.event_date, e.event_time, v.name as venue_name
            FROM bookings b JOIN events e ON b.event_id=e.id
            LEFT JOIN venues v ON e.venue_id=v.id
            WHERE REPLACE(b.code,'-','')=? AND e.organizer_id=?
        """, (clean, org_id)).fetchone()
        if booking:
            already = booking["verified"] == 1
            if not already:
                conn.execute("UPDATE bookings SET verified=1, verified_at=? WHERE id=?",
                             (datetime.now().isoformat(), booking["id"]))
                conn.commit()
            result = {"status": "already" if already else "success", "booking": dict(booking)}
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
        name     = request.form["name"].strip()
        email    = request.form["email"].strip().lower()
        phone    = request.form.get("phone","").strip()
        password = request.form["password"]
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("user_register.html")
        conn = get_db()
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            conn.close(); flash("An account with this email already exists.", "error")
            return render_template("user_register.html")
        conn.execute(
            "INSERT INTO users (id,name,email,password_hash,phone,created_at) VALUES(?,?,?,?,?,?)",
            (new_id(), name, email, generate_password_hash(password), phone, datetime.now().isoformat()))
        conn.commit(); conn.close()
        flash("Account created! Please log in.", "success")
        return redirect(url_for("user_login"))
    return render_template("user_register.html")


@app.route("/login", methods=["GET", "POST"])
def user_login():
    if session.get("user_id"):
        return redirect(url_for("book_list"))
    if request.method == "POST":
        email    = request.form["email"].strip().lower()
        password = request.form["password"]
        conn     = get_db()
        user     = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
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
# USER — MY TICKETS
# ═══════════════════════════════════════════════════════════════

@app.route("/my-tickets")
@require_user
def my_tickets():
    user_id = session["user_id"]
    conn    = get_db()
    bookings = conn.execute("""
        SELECT b.*, e.title as event_title, e.event_date, e.event_time,
               v.name as venue_name, v.location as venue_location,
               o.org_name as organizer_name
        FROM bookings b
        JOIN events e ON b.event_id=e.id
        LEFT JOIN venues v ON e.venue_id=v.id
        LEFT JOIN organizers o ON e.organizer_id=o.id
        WHERE b.user_id=?
        ORDER BY e.event_date DESC
    """, (user_id,)).fetchall()
    conn.close()
    today = date.today().isoformat()
    upcoming = [b for b in bookings if b["event_date"] >= today]
    past     = [b for b in bookings if b["event_date"] <  today]
    return render_template("my_tickets.html", upcoming=upcoming, past=past)


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
    conn   = get_db()
    events = conn.execute("""
        SELECT e.*, v.name as venue_name, v.capacity, o.org_name as organizer_name
        FROM events e
        LEFT JOIN venues v ON e.venue_id=v.id
        LEFT JOIN organizers o ON e.organizer_id=o.id
        WHERE e.event_date>=? AND e.status='active'
        ORDER BY e.event_date ASC
    """, (date.today().isoformat(),)).fetchall()

    events_data = []
    for ev in events:
        booked = len(get_booked_seats(ev["id"]))
        cover  = conn.execute(
            "SELECT filename FROM event_photos WHERE event_id=? ORDER BY created_at LIMIT 1",
            (ev["id"],)).fetchone()
        # min tier price for display
        min_tier = conn.execute(
            "SELECT MIN(price) as mp FROM seat_tiers WHERE event_id=?", (ev["id"],)).fetchone()
        has_tiers   = min_tier and min_tier["mp"] is not None
        display_price = min_tier["mp"] if has_tiers else ev["price"]
        events_data.append({
            **dict(ev), "booked": booked,
            "cover": cover["filename"] if cover else None,
            "display_price": display_price,
            "has_tiers": has_tiers,
        })
    conn.close()
    return render_template("book.html", events=events_data)


@app.route("/book/<event_id>", methods=["GET", "POST"])
def book_event(event_id):
    conn  = get_db()
    event = conn.execute("""
        SELECT e.*, v.name as venue_name, v.location as venue_location,
               v.rows, v.seats_per_row, v.capacity, v.id as venue_db_id,
               o.org_name as organizer_name
        FROM events e
        LEFT JOIN venues v ON e.venue_id=v.id
        LEFT JOIN organizers o ON e.organizer_id=o.id
        WHERE e.id=? AND e.status='active'
    """, (event_id,)).fetchone()

    if not event:
        conn.close(); flash("Event not found.", "error")
        return redirect(url_for("book_list"))

    booked_seats = get_booked_seats(event_id)
    tiers        = [dict(r) for r in conn.execute("SELECT * FROM seat_tiers WHERE event_id=? ORDER BY row_from", (event_id,)).fetchall()]
    performers   = conn.execute("SELECT * FROM performers WHERE event_id=? ORDER BY created_at", (event_id,)).fetchall()
    event_photos = conn.execute("SELECT * FROM event_photos WHERE event_id=? ORDER BY created_at DESC", (event_id,)).fetchall()
    venue_photos = conn.execute("SELECT * FROM venue_photos WHERE venue_id=? ORDER BY created_at DESC",
                                (event["venue_db_id"],)).fetchall() if event["venue_db_id"] else []

    if request.method == "POST":
        seats_str = request.form.get("selected_seats","")
        seats     = [s.strip() for s in seats_str.split(",") if s.strip()]
        if not seats:
            flash("Please select at least one seat.", "error")
            conn.close(); return redirect(url_for("book_event", event_id=event_id))
        for s in seats:
            if s in booked_seats:
                flash(f"Seat {s} was just taken. Please reselect.", "error")
                conn.close(); return redirect(url_for("book_event", event_id=event_id))

        total, _ = calc_seat_total(seats, tiers, event["price"])
        booking_id = new_id()
        user_id    = session.get("user_id")
        conn.execute(
            "INSERT INTO bookings (id,event_id,user_id,code,customer_name,customer_email,customer_phone,seats,total_amount,booked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (booking_id, event_id, user_id, generate_ticket_code(),
             request.form["customer_name"], request.form.get("customer_email",""),
             request.form["customer_phone"], ", ".join(seats),
             total, datetime.now().isoformat()))
        conn.commit(); conn.close()
        flash("Booking confirmed!", "success")
        return redirect(url_for("view_ticket", booking_id=booking_id))

    conn.close()
    return render_template("book_event.html", event=event, booked_seats=booked_seats,
                           tiers=tiers, performers=performers,
                           event_photos=event_photos, venue_photos=venue_photos)


@app.route("/ticket/<booking_id>")
def view_ticket(booking_id):
    conn    = get_db()
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        conn.close(); flash("Booking not found.", "error")
        return redirect(url_for("book_list"))
    event = conn.execute("""
        SELECT e.*, v.name as venue_name, v.location as venue_location, o.org_name as organizer_name
        FROM events e LEFT JOIN venues v ON e.venue_id=v.id
        LEFT JOIN organizers o ON e.organizer_id=o.id WHERE e.id=?
    """, (booking["event_id"],)).fetchone()
    conn.close()
    qr_b64 = generate_qr_base64(f"SHOWRUNNER|{booking['code']}|{booking['customer_name']}|{booking['seats']}")
    return render_template("ticket.html", booking=booking, event=event, qr_base64=qr_b64)


# ─── API ─────────────────────────────────────────────────────

@app.route("/api/booked-seats/<event_id>")
def api_booked_seats(event_id):
    return jsonify(get_booked_seats(event_id))


@app.route("/api/event-tiers/<event_id>")
def api_event_tiers(event_id):
    conn  = get_db()
    tiers = [dict(r) for r in conn.execute("SELECT * FROM seat_tiers WHERE event_id=? ORDER BY row_from", (event_id,)).fetchall()]
    conn.close()
    return jsonify(tiers)


# ─── Run ─────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
