import sqlite3
from datetime import datetime, timedelta
import bcrypt

# Create airline customer service database for a single Indian user
conn = sqlite3.connect("airline_customers.db")
cur = conn.cursor()

# Customers table - Multiple users with authentication
cur.execute("""
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    passport_number TEXT,
    frequent_flyer_number TEXT,
    nationality TEXT DEFAULT 'Indian',
    status TEXT DEFAULT 'Active'
)
""")

# Flights table - Indian domestic and international flights
cur.execute("""
CREATE TABLE IF NOT EXISTS flights (
    flight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_number TEXT NOT NULL,
    airline TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    departure_time TEXT NOT NULL,
    arrival_time TEXT NOT NULL,
    price REAL NOT NULL,
    available_seats INTEGER NOT NULL,
    aircraft_type TEXT,
    flight_type TEXT DEFAULT 'Domestic'
)
""")

# Bookings table
cur.execute("""
CREATE TABLE IF NOT EXISTS bookings (
    booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    flight_id INTEGER NOT NULL,
    booking_date TEXT NOT NULL,
    seat_number TEXT,
    booking_status TEXT DEFAULT 'Confirmed',
    total_price REAL NOT NULL,
    pnr TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (flight_id) REFERENCES flights(flight_id)
)
""")

# Payments table
cur.execute("""
CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    payment_method TEXT NOT NULL,
    payment_date TEXT NOT NULL,
    payment_status TEXT DEFAULT 'Completed',
    FOREIGN KEY (booking_id) REFERENCES bookings(booking_id)
)
""")

# Insert multiple Indian customers with hashed passwords
# Default password for all users: "password123"
default_password = "password123"
password_hash = bcrypt.hashpw(default_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

customers = [
    ("Aadhvik Kosireddy", "aadhvik@email.com", "+91-98765-43210", password_hash, "M1234567", "FF789012", "Indian", "Active"),
    ("Priya Sharma", "priya.sharma@email.com", "+91-98765-43211", password_hash, "M2345678", "FF890123", "Indian", "Active"),
    ("Rahul Verma", "rahul.verma@email.com", "+91-98765-43212", password_hash, "M3456789", "FF901234", "Indian", "Active"),
    ("Ananya Reddy", "ananya.reddy@email.com", "+91-98765-43213", password_hash, "M4567890", "FF012345", "Indian", "Active"),
    ("Vikram Singh", "vikram.singh@email.com", "+91-98765-43214", password_hash, "M5678901", "FF123456", "Indian", "Active"),
]

cur.executemany("""
INSERT INTO customers (name, email, phone, password_hash, passport_number, frequent_flyer_number, nationality, status)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", customers)

# Insert Indian domestic and international flights
base_date = datetime.now()
flights = [
    # Domestic Flights
    ("AI101", "Air India", "Delhi (DEL)", "Mumbai (BOM)", 
     (base_date + timedelta(days=1, hours=8)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=1, hours=10, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     5500.00, 45, "Boeing 737", "Domestic"),
    
    ("6E203", "IndiGo", "Mumbai (BOM)", "Bengaluru (BLR)",
     (base_date + timedelta(days=2, hours=14)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=2, hours=16)).strftime("%Y-%m-%d %H:%M"),
     4200.00, 52, "Airbus A320", "Domestic"),
    
    ("SG305", "SpiceJet", "Bengaluru (BLR)", "Hyderabad (HYD)",
     (base_date + timedelta(days=3, hours=11)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=3, hours=12, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     3800.00, 38, "Boeing 737", "Domestic"),
    
    ("AI407", "Air India", "Hyderabad (HYD)", "Chennai (MAA)",
     (base_date + timedelta(days=4, hours=9)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=4, hours=10, minutes=45)).strftime("%Y-%m-%d %H:%M"),
     4500.00, 41, "Airbus A320", "Domestic"),
    
    ("UK509", "Vistara", "Delhi (DEL)", "Kolkata (CCU)",
     (base_date + timedelta(days=5, hours=7)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=5, hours=9, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     6200.00, 48, "Airbus A321", "Domestic"),
    
    # International Flights
    ("AI191", "Air India", "Delhi (DEL)", "Dubai (DXB)",
     (base_date + timedelta(days=6, hours=22)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=7, hours=1, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     18500.00, 28, "Boeing 787", "International"),
    
    ("EK512", "Emirates", "Mumbai (BOM)", "Dubai (DXB)",
     (base_date + timedelta(days=7, hours=3)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=7, hours=6, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     22000.00, 35, "Airbus A380", "International"),
    
    ("AI173", "Air India", "Delhi (DEL)", "Singapore (SIN)",
     (base_date + timedelta(days=8, hours=23, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=9, hours=6, minutes=45)).strftime("%Y-%m-%d %H:%M"),
     28500.00, 24, "Boeing 777", "International"),
    
    ("SQ401", "Singapore Airlines", "Mumbai (BOM)", "Singapore (SIN)",
     (base_date + timedelta(days=9, hours=2)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=9, hours=9, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     32000.00, 30, "Airbus A350", "International"),
    
    ("AI191", "Air India", "Delhi (DEL)", "London (LHR)",
     (base_date + timedelta(days=10, hours=14)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=10, hours=23, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     65000.00, 22, "Boeing 787", "International"),
    
    ("BA256", "British Airways", "Mumbai (BOM)", "London (LHR)",
     (base_date + timedelta(days=11, hours=2, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=11, hours=12)).strftime("%Y-%m-%d %H:%M"),
     72000.00, 26, "Boeing 787", "International"),
    
    ("AI127", "Air India", "Delhi (DEL)", "New York (JFK)",
     (base_date + timedelta(days=12, hours=21)).strftime("%Y-%m-%d %H:%M"),
     (base_date + timedelta(days=13, hours=13, minutes=30)).strftime("%Y-%m-%d %H:%M"),
     85000.00, 18, "Boeing 777", "International"),
]

cur.executemany("""
INSERT INTO flights (flight_number, airline, origin, destination, departure_time, arrival_time, price, available_seats, aircraft_type, flight_type)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", flights)

# Insert bookings for multiple users
bookings = [
    # Aadhvik's bookings
    (1, 1, (base_date - timedelta(days=30)).strftime("%Y-%m-%d"), "12A", "Completed", 5500.00, "PNR123456"),
    (1, 6, (base_date - timedelta(days=15)).strftime("%Y-%m-%d"), "8F", "Completed", 18500.00, "PNR234567"),
    (1, 2, (base_date - timedelta(days=2)).strftime("%Y-%m-%d"), "15C", "Confirmed", 4200.00, "PNR345678"),
    
    # Priya's bookings
    (2, 3, (base_date - timedelta(days=20)).strftime("%Y-%m-%d"), "14B", "Completed", 3800.00, "PNR567890"),
    (2, 7, (base_date - timedelta(days=1)).strftime("%Y-%m-%d"), "22F", "Confirmed", 22000.00, "PNR678901"),
    
    # Rahul's bookings
    (3, 4, (base_date - timedelta(days=25)).strftime("%Y-%m-%d"), "18C", "Completed", 4500.00, "PNR789012"),
    (3, 10, (base_date - timedelta(days=1)).strftime("%Y-%m-%d"), "24A", "Confirmed", 65000.00, "PNR890123"),
    
    # Ananya's bookings
    (4, 5, (base_date - timedelta(days=18)).strftime("%Y-%m-%d"), "10A", "Completed", 6200.00, "PNR901234"),
    
    # Vikram's bookings
    (5, 8, (base_date - timedelta(days=10)).strftime("%Y-%m-%d"), "16D", "Completed", 28500.00, "PNR012345"),
]

cur.executemany("""
INSERT INTO bookings (customer_id, flight_id, booking_date, seat_number, booking_status, total_price, pnr)
VALUES (?, ?, ?, ?, ?, ?, ?)
""", bookings)

# Insert payments for all bookings
payments = [
    (1, 5500.00, "UPI", (base_date - timedelta(days=30)).strftime("%Y-%m-%d"), "Completed"),
    (2, 18500.00, "Credit Card", (base_date - timedelta(days=15)).strftime("%Y-%m-%d"), "Completed"),
    (3, 4200.00, "Debit Card", (base_date - timedelta(days=2)).strftime("%Y-%m-%d"), "Completed"),
    (4, 3800.00, "UPI", (base_date - timedelta(days=20)).strftime("%Y-%m-%d"), "Completed"),
    (5, 22000.00, "Credit Card", (base_date - timedelta(days=1)).strftime("%Y-%m-%d"), "Completed"),
    (6, 4500.00, "Net Banking", (base_date - timedelta(days=25)).strftime("%Y-%m-%d"), "Completed"),
    (7, 65000.00, "Debit Card", (base_date - timedelta(days=1)).strftime("%Y-%m-%d"), "Completed"),
    (8, 6200.00, "UPI", (base_date - timedelta(days=18)).strftime("%Y-%m-%d"), "Completed"),
    (9, 28500.00, "Credit Card", (base_date - timedelta(days=10)).strftime("%Y-%m-%d"), "Completed"),
]

cur.executemany("""
INSERT INTO payments (booking_id, amount, payment_method, payment_date, payment_status)
VALUES (?, ?, ?, ?, ?)
""", payments)

conn.commit()
conn.close()

print("✅ Airline customer service database created successfully!")
print("Database: airline_customers.db")
print(f"- {len(customers)} customers added with authentication")
print(f"- {len(flights)} flights added (5 Domestic + 7 International)")
print(f"- {len(bookings)} bookings added across all users")
print(f"- {len(payments)} payments added")
print("\n🔐 Login Credentials (all users):")
print("   Password: password123")
print("\n📧 User Emails:")
for name, email, *_ in customers:
    print(f"   - {name}: {email}")
