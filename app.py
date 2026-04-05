import os
import json
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
    url_for, flash, jsonify, session, make_response, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    PUSH_AVAILABLE = True
except ImportError:
    PUSH_AVAILABLE = False

VAPID_PRIVATE_KEY = None
VAPID_PUBLIC_KEY  = None
VAPID_CLAIMS      = {"sub": "mailto:admin@showrunner.app"}

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
            tagline TEXT,
            logo TEXT,
            brand_color TEXT DEFAULT '#f5c842',
            phone TEXT,
            website TEXT,
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
            row_config TEXT,
            row_names TEXT,
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
            cover_photo TEXT,
            payment_info TEXT,
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

        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


init_db()

# ── Live DB migrations ────────────────────────────────────────
for _col, _sql in [
    ("row_names",    "ALTER TABLE venues ADD COLUMN row_names TEXT"),
    ("tagline",      "ALTER TABLE organizers ADD COLUMN tagline TEXT"),
    ("logo",         "ALTER TABLE organizers ADD COLUMN logo TEXT"),
    ("brand_color",  "ALTER TABLE organizers ADD COLUMN brand_color TEXT DEFAULT '#f5c842'"),
    ("phone",        "ALTER TABLE organizers ADD COLUMN phone TEXT"),
    ("website",      "ALTER TABLE organizers ADD COLUMN website TEXT"),
    ("cover_photo",  "ALTER TABLE events ADD COLUMN cover_photo TEXT"),
    ("payment_info", "ALTER TABLE events ADD COLUMN payment_info TEXT"),
]:
    try:
        _c = get_db(); _c.execute(_sql); _c.commit(); _c.close()
    except Exception:
        pass  # column already exists

for sub in ("venues", "events", "performers", "logos"):
    os.makedirs(os.path.join(UPLOAD_FOLDER, sub), exist_ok=True)


# ─── PWA: Icons ──────────────────────────────────────────────
def generate_pwa_icons():
    """Generate minimal app icons on first run using Pillow."""
    try:
        from PIL import Image, ImageDraw
        icon_dir = os.path.join(os.path.dirname(__file__), "static", "icons")
        os.makedirs(icon_dir, exist_ok=True)

        for size in [192, 512]:
            path = os.path.join(icon_dir, f"icon-{size}.png")
            if os.path.exists(path):
                continue

            img  = Image.new("RGBA", (size, size), (13, 13, 26, 255))
            draw = ImageDraw.Draw(img)

            # Gold outer circle
            p = int(size * 0.08)
            draw.ellipse([p, p, size - p, size - p], fill=(245, 200, 66, 255))

            # Dark inner circle
            p2 = int(size * 0.20)
            draw.ellipse([p2, p2, size - p2, size - p2], fill=(13, 13, 26, 255))

            # Microphone body (rounded rect approximated with ellipse + rect)
            cx    = size // 2
            mw    = int(size * 0.13)
            mh    = int(size * 0.24)
            mtop  = int(size * 0.28)
            mbot  = mtop + mh
            lw    = max(2, int(size * 0.025))

            # Mic capsule: filled rounded shape
            draw.rectangle([cx - mw, mtop + mw, cx + mw, mbot - mw], fill=(245, 200, 66, 255))
            draw.ellipse([cx - mw, mtop, cx + mw, mtop + mw * 2], fill=(245, 200, 66, 255))
            draw.ellipse([cx - mw, mbot - mw * 2, cx + mw, mbot], fill=(245, 200, 66, 255))

            # Mic stand line
            stand_top = mbot
            stand_bot = mbot + int(size * 0.10)
            draw.line([cx, stand_top, cx, stand_bot], fill=(245, 200, 66, 255), width=lw)

            # Base bar
            bw = int(size * 0.15)
            draw.line([cx - bw, stand_bot, cx + bw, stand_bot], fill=(245, 200, 66, 255), width=lw)

            img.save(path, "PNG")

        # Tiny badge icon (monochrome circle)
        badge_path = os.path.join(icon_dir, "icon-badge.png")
        if not os.path.exists(badge_path):
            img  = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([4, 4, 92, 92], fill=(245, 200, 66, 255))
            img.save(badge_path, "PNG")

    except Exception:
        pass  # Icons are optional; app works without them


generate_pwa_icons()


# ─── PWA: VAPID Keys ─────────────────────────────────────────
def init_vapid():
    global VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY
    if not PUSH_AVAILABLE:
        return
    keys_file = os.path.join(os.path.dirname(__file__), "vapid_keys.json")
    if os.path.exists(keys_file):
        with open(keys_file) as f:
            keys = json.load(f)
        VAPID_PRIVATE_KEY = keys["private_key"]
        VAPID_PUBLIC_KEY  = keys["public_key"]
        return
    try:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        v = Vapid()
        v.generate_keys()
        VAPID_PRIVATE_KEY = v.private_pem().decode("utf-8")
        raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        VAPID_PUBLIC_KEY  = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
        with open(keys_file, "w") as f:
            json.dump({"private_key": VAPID_PRIVATE_KEY, "public_key": VAPID_PUBLIC_KEY}, f)
    except Exception:
        pass


init_vapid()


# ─── PWA: Send Push Notification ────────────────────────────
def send_push_to_user(user_id, title, body, url="/"):
    if not PUSH_AVAILABLE or not VAPID_PRIVATE_KEY:
        return
    conn  = get_db()
    subs  = conn.execute(
        "SELECT * FROM push_subscriptions WHERE user_id=?", (user_id,)
    ).fetchall()
    conn.close()
    payload = json.dumps({"title": title, "body": body, "url": url})
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=dict(VAPID_CLAIMS),
            )
        except Exception:
            pass


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


def parse_row_config(venue):
    """Return {row_letter: seat_count} dict for a venue row.
    Falls back to uniform seats_per_row if row_config is NULL."""
    if venue["row_config"]:
        try:
            return json.loads(venue["row_config"])
        except Exception:
            pass
    letters = list(LABELS[:venue["rows"]])
    return {l: venue["seats_per_row"] for l in letters}


def parse_row_names(venue):
    """Return {row_letter: display_name} dict. Empty dict if not set."""
    try:
        if venue["row_names"]:
            return json.loads(venue["row_names"])
    except Exception:
        pass
    return {}


def row_config_capacity(cfg):
    return sum(cfg.values())


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

import markupsafe
def nl2br(value):
    if not value:
        return ""
    escaped = markupsafe.escape(value)
    return markupsafe.Markup(str(escaped).replace("\n", "<br>"))
app.jinja_env.filters["nl2br"] = nl2br


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

@app.route("/org/profile", methods=["GET", "POST"])
@require_organizer
def org_profile():
    org_id = session["organizer_id"]
    conn   = get_db()
    org    = conn.execute("SELECT * FROM organizers WHERE id=?", (org_id,)).fetchone()
    if request.method == "POST":
        org_name    = request.form.get("org_name", "").strip()
        tagline     = request.form.get("tagline", "").strip()
        phone       = request.form.get("phone", "").strip()
        website     = request.form.get("website", "").strip()
        brand_color = request.form.get("brand_color", "#f5c842").strip()

        logo_path = org["logo"]
        new_logo  = save_upload(request.files.get("logo"), "logos")
        if new_logo:
            if logo_path:
                delete_upload(logo_path)
            logo_path = new_logo

        conn.execute("""
            UPDATE organizers SET org_name=?, tagline=?, phone=?, website=?, brand_color=?, logo=?
            WHERE id=?
        """, (org_name or org["org_name"], tagline, phone, website, brand_color, logo_path, org_id))
        conn.commit(); conn.close()
        flash("Brand profile updated!", "success")
        return redirect(url_for("org_profile"))

    conn.close()
    return render_template("org_profile.html", org=org)


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
        eid         = new_id()
        cover_photo = save_upload(request.files.get("cover_photo"), "events")
        payment_info = request.form.get("payment_info", "").strip()
        conn.execute(
            "INSERT INTO events (id,organizer_id,title,description,event_date,event_time,venue_id,price,cover_photo,payment_info,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (eid, org_id, request.form["title"], request.form.get("description",""),
             request.form["event_date"], request.form["event_time"],
             request.form["venue_id"], float(request.form["price"]),
             cover_photo, payment_info, datetime.now().isoformat()))
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
               v.rows, v.seats_per_row, v.capacity, v.row_config
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
    venue_row_names = {}
    if event["venue_id"]:
        _v = conn.execute("SELECT row_names FROM venues WHERE id=?", (event["venue_id"],)).fetchone()
        if _v:
            venue_row_names = parse_row_names(_v)
    conn.close()
    booked_seats = get_booked_seats(event_id)
    row_letters  = list(LABELS[:event["rows"]]) if event["rows"] else []
    row_config   = parse_row_config(event)
    return render_template("event_detail.html", event=event, bookings=bookings,
                           booked_seats=booked_seats, performers=performers,
                           photos=photos, tiers=tiers, row_letters=row_letters,
                           row_config=row_config, row_names=venue_row_names)


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
    import json
    org_id = session["organizer_id"]
    if request.method == "POST":
        rows          = int(request.form["rows"])
        seats_per_row = int(request.form["seats_per_row"])
        # Build initial uniform row_config
        cfg = {LABELS[i]: seats_per_row for i in range(rows)}
        conn = get_db()
        vid  = new_id()
        conn.execute(
            "INSERT INTO venues (id,organizer_id,name,location,rows,seats_per_row,capacity,row_config,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (vid, org_id, request.form["name"], request.form["location"],
             rows, seats_per_row, rows * seats_per_row,
             json.dumps(cfg), datetime.now().isoformat()))
        conn.commit(); conn.close()
        flash("Venue created! Now customise each row's seat count.", "success")
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
    photos     = conn.execute("SELECT * FROM venue_photos WHERE venue_id=? ORDER BY created_at DESC", (venue_id,)).fetchall()
    conn.close()
    row_config = parse_row_config(venue)
    row_names  = parse_row_names(venue)
    return render_template("venue_detail.html", venue=venue, photos=photos,
                           row_config=row_config, row_names=row_names)


@app.route("/org/venues/<venue_id>/rows", methods=["POST"])
@require_organizer
def org_update_venue_rows(venue_id):
    import json
    org_id = session["organizer_id"]
    conn   = get_db()
    venue  = conn.execute("SELECT * FROM venues WHERE id=? AND organizer_id=?", (venue_id, org_id)).fetchone()
    if not venue:
        conn.close(); flash("Venue not found.", "error")
        return redirect(url_for("org_venues_list"))

    seat_counts = request.form.getlist("row_seats")
    name_list   = request.form.getlist("row_name")

    cfg   = {}
    names = {}
    for i, cnt_str in enumerate(seat_counts):
        if i >= 26:
            break
        letter = LABELS[i]
        try:
            cnt = max(1, min(100, int(cnt_str)))
        except ValueError:
            cnt = 8
        cfg[letter] = cnt
        if i < len(name_list) and name_list[i].strip():
            names[letter] = name_list[i].strip()

    if not cfg:
        flash("At least one row is required.", "error")
        conn.close()
        return redirect(url_for("org_venue_detail", venue_id=venue_id))

    new_rows = len(cfg)
    capacity = row_config_capacity(cfg)
    conn.execute(
        "UPDATE venues SET rows=?, row_config=?, row_names=?, capacity=? WHERE id=?",
        (new_rows, json.dumps(cfg), json.dumps(names), capacity, venue_id))
    conn.commit(); conn.close()
    flash("Seat layout saved!", "success")
    return redirect(url_for("org_venue_detail", venue_id=venue_id))


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
        SELECT e.*, v.name as venue_name, v.capacity,
               o.org_name as organizer_name, o.brand_color as org_brand_color, o.logo as org_logo
        FROM events e
        LEFT JOIN venues v ON e.venue_id=v.id
        LEFT JOIN organizers o ON e.organizer_id=o.id
        WHERE e.event_date>=? AND e.status='active'
        ORDER BY e.event_date ASC
    """, (date.today().isoformat(),)).fetchall()

    events_data = []
    for ev in events:
        booked = len(get_booked_seats(ev["id"]))
        # Use event cover_photo first, fall back to first gallery photo
        cover = ev["cover_photo"]
        if not cover:
            gallery = conn.execute(
                "SELECT filename FROM event_photos WHERE event_id=? ORDER BY created_at LIMIT 1",
                (ev["id"],)).fetchone()
            cover = gallery["filename"] if gallery else None
        min_tier = conn.execute(
            "SELECT MIN(price) as mp FROM seat_tiers WHERE event_id=?", (ev["id"],)).fetchone()
        has_tiers     = min_tier and min_tier["mp"] is not None
        display_price = min_tier["mp"] if has_tiers else ev["price"]
        events_data.append({
            **dict(ev), "booked": booked,
            "cover": cover,
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
               v.rows, v.seats_per_row, v.capacity, v.row_config, v.id as venue_db_id,
               o.org_name as organizer_name, o.brand_color as org_brand_color,
               o.logo as org_logo, o.tagline as org_tagline,
               o.phone as org_phone, o.website as org_website
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

    row_config = parse_row_config(event)
    conn.close()
    return render_template("book_event.html", event=event, booked_seats=booked_seats,
                           tiers=tiers, performers=performers,
                           event_photos=event_photos, venue_photos=venue_photos,
                           row_config=row_config)


@app.route("/ticket/<booking_id>")
def view_ticket(booking_id):
    conn    = get_db()
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        conn.close(); flash("Booking not found.", "error")
        return redirect(url_for("book_list"))
    event = conn.execute("""
        SELECT e.*, v.name as venue_name, v.location as venue_location,
               o.org_name as organizer_name, o.brand_color as org_brand_color, o.logo as org_logo
        FROM events e LEFT JOIN venues v ON e.venue_id=v.id
        LEFT JOIN organizers o ON e.organizer_id=o.id WHERE e.id=?
    """, (booking["event_id"],)).fetchone()
    conn.close()
    qr_b64 = generate_qr_base64(f"SHOWRUNNER|{booking['code']}|{booking['customer_name']}|{booking['seats']}")
    return render_template("ticket.html", booking=booking, event=event, qr_base64=qr_b64)


# ─── PWA Routes ──────────────────────────────────────────────

@app.route("/sw.js")
def service_worker():
    resp = make_response(send_from_directory("static", "sw.js"))
    resp.headers["Content-Type"]          = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"]          = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/manifest.json")
def web_manifest():
    resp = make_response(send_from_directory("static", "manifest.json"))
    resp.headers["Content-Type"] = "application/manifest+json"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/offline")
def offline_page():
    return render_template("offline.html")


@app.route("/api/push/vapid-public-key")
def push_vapid_key():
    if not PUSH_AVAILABLE or not VAPID_PUBLIC_KEY:
        return jsonify({"key": None})
    return jsonify({"key": VAPID_PUBLIC_KEY})


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    if not PUSH_AVAILABLE:
        return jsonify({"ok": False, "error": "Push not configured"}), 200
    data     = request.get_json(force=True)
    endpoint = data.get("endpoint")
    p256dh   = data.get("keys", {}).get("p256dh")
    auth     = data.get("keys", {}).get("auth")
    if not endpoint or not p256dh or not auth:
        return jsonify({"ok": False, "error": "Invalid subscription"}), 400
    user_id = session.get("user_id")
    conn    = get_db()
    existing = conn.execute("SELECT id FROM push_subscriptions WHERE endpoint=?", (endpoint,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE push_subscriptions SET p256dh=?, auth=?, user_id=? WHERE endpoint=?",
            (p256dh, auth, user_id, endpoint)
        )
    else:
        conn.execute(
            "INSERT INTO push_subscriptions (id,user_id,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)",
            (new_id(), user_id, endpoint, p256dh, auth, datetime.now().isoformat())
        )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    data     = request.get_json(force=True)
    endpoint = data.get("endpoint")
    if endpoint:
        conn = get_db()
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
        conn.commit(); conn.close()
    return jsonify({"ok": True})


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
