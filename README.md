# 🎤 ShowRunner — Event & Ticket Management System

A complete event management and digital ticketing system built for comedians, MCs, and event organizers.

---

## Features

### Admin Side
- **Dashboard** — Overview of events, bookings, revenue, and verification stats
- **Events** — Create, view, and delete shows with pricing and venue assignment
- **Venues** — Add venues with custom seating layouts (rows × seats per row)
- **Bookings** — View all bookings across events with status tracking
- **Verify** — Enter a ticket code at the entrance to verify guests

### Customer Side
- **Book Ticket** — Browse upcoming events, select seats from an interactive seat map
- **Digital Ticket** — Receive a ticket with a unique code + QR code for entry
- **Screenshot & Show** — Guest shows ticket code or QR at the door

### Verification Flow
1. Customer books tickets → gets a unique code like `ABCD-EFGH-JKLM`
2. Customer screenshots their digital ticket (with QR code)
3. At the entrance, staff goes to **Verify** tab
4. Staff enters the ticket code → system confirms validity
5. System marks ticket as verified (prevents double entry)

---

## Setup & Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)

### Step 1: Install Dependencies
```bash
cd showrunner
pip install -r requirements.txt
```

### Step 2: Run the Application
```bash
python app.py
```

### Step 3: Open in Browser
```
http://localhost:5000
```

---

## Project Structure

```
showrunner/
├── app.py                  # Flask application (routes, database, logic)
├── requirements.txt        # Python dependencies
├── showrunner.db           # SQLite database (auto-created on first run)
├── static/
│   ├── css/
│   │   └── style.css       # Complete stylesheet
│   └── js/
│       └── app.js          # Seat map & client-side interactions
└── templates/
    ├── base.html           # Base layout with nav
    ├── dashboard.html      # Dashboard with stats
    ├── events.html         # Events list
    ├── create_event.html   # New event form
    ├── event_detail.html   # Event detail with seat map & bookings
    ├── venues.html         # Venues list with seat maps
    ├── create_venue.html   # New venue form
    ├── book.html           # Customer: browse events
    ├── book_event.html     # Customer: select seats & book
    ├── ticket.html         # Digital ticket with QR code
    ├── bookings.html       # All bookings list
    └── verify.html         # Ticket verification page
```

---

## Tech Stack

- **Backend:** Flask (Python)
- **Database:** SQLite
- **Frontend:** HTML, CSS, JavaScript
- **QR Codes:** qrcode + Pillow libraries
- **Fonts:** DM Sans, Space Mono, JetBrains Mono (Google Fonts)

---

## Default Data

The system comes preloaded with two sample venues:
- **Mikumi Comedy Lounge** — Dar es Salaam (6 rows × 8 seats = 48 capacity)
- **Kariakoo Open Stage** — Kariakoo, Dar es Salaam (4 rows × 10 seats = 40 capacity)

---

## Currency

The system uses **TZS (Tanzanian Shilling)** by default. To change the currency, search and replace `TZS` in the templates and Python files.

---

## Tips for Production Deployment

1. Set `debug=False` in `app.py` for production
2. Use a proper WSGI server like **Gunicorn**: `gunicorn app:app`
3. Consider adding user authentication for admin pages
4. Back up `showrunner.db` regularly
5. For high traffic, migrate from SQLite to PostgreSQL

---

Built with ❤️ for the comedy community
