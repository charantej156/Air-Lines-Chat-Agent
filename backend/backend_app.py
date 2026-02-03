import os
import warnings
import sys
import json
import sqlite3
import os
import traceback
from typing import List, Optional, Union
from datetime import datetime, timedelta
import bcrypt
import jwt

# Optional imports which may fail in some environments
try:
    import PyPDF2
except Exception:
    PyPDF2 = None

try:
    import faiss
except Exception:
    faiss = None

try:
    import numpy as np
except Exception:
    np = None

# Skip sentence_transformers to avoid PyTorch DLL loading issues
SentenceTransformer = None

# new OpenAI client package import (keeps your original style)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# -------------------------------
# 0. Environment / warnings
# -------------------------------
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Config via environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PDF_PATH = os.getenv("PDF_PATH", "").strip()  # optional path to load at startup
FAISS_DIM = int(os.getenv("FAISS_DIM", "384"))
RAG_K = int(os.getenv("RAG_K", "2"))

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# -------------------------------
# 1. OpenAI Client (safe)
# -------------------------------
client = None
if OpenAI is not None and OPENAI_API_KEY:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        client = None

# -------------------------------
# 2. Embedding + FAISS (lazy init)
# -------------------------------
class FallbackEmbedder:
    """A tiny fallback embedder that uses a deterministic hash to produce floats when real models are unavailable."""
    def __init__(self, dim=FAISS_DIM):
        self.dim = dim

    def _text_to_vector(self, text: str) -> List[float]:
        # deterministic pseudo-embedding based on hash -- stable but not semantically meaningful
        h = abs(hash(text))
        vec = []
        for i in range(self.dim):
            # produce deterministic pseudo-random floats in [0, 1)
            h = (h * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
            vec.append(((h % 10000) / 10000.0))
        return vec

    def embed(self, texts: Union[List[str], str]):
        if isinstance(texts, str):
            texts = [texts]
        return np.array([self._text_to_vector(t) for t in texts], dtype=np.float32)

class LocalEmbedder:
    def __init__(self, model_name="all-MiniLM-L6-v2", dim=FAISS_DIM):
        self.model_name = model_name
        self.dim = dim
        if SentenceTransformer is None:
            raise RuntimeError("sentence_transformers not available")
        # If SentenceTransformer raises an error (e.g. missing model files), propagate to caller
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: Union[List[str], str]):
        if isinstance(texts, str):
            texts = [texts]
        # convert_to_numpy=True ensures numpy arrays
        return self.model.encode(texts, convert_to_numpy=True)

class FaissVectorDB:
    def __init__(self, embedder, dim=FAISS_DIM):
        self.embedder = embedder
        self.dim = dim
        self.index = None
        self.docs: List[str] = []
        # initialize index only if faiss and numpy are present
        if faiss is not None and np is not None:
            try:
                self.index = faiss.IndexFlatL2(dim)
            except Exception:
                self.index = None

    def add(self, docs: List[str]):
        if not docs:
            return
        vecs = self.embedder.embed(docs)
        if self.index is None:
            # can't add vectors to a non-existent index; store docs but skip vector storage
            self.docs.extend(docs)
            return
        # ensure vecs shape
        if isinstance(vecs, list):
            vecs = np.array(vecs, dtype=np.float32)
        self.index.add(vecs)
        self.docs.extend(docs)

    def search(self, query: str, k=3) -> List[str]:
        if not self.docs:
            return []
        try:
            qvec = self.embedder.embed([query])
            if self.index is None:
                # return naive substring matches when no vector index available
                matches = [d for d in self.docs if query.lower() in d.lower()]
                return matches[:k]
            D, I = self.index.search(qvec, k)
            results = []
            for i in I[0]:
                if i < len(self.docs):
                    results.append(self.docs[i])
            return results
        except Exception:
            # on any error, fallback to substring search
            matches = [d for d in self.docs if query.lower() in d.lower()]
            return matches[:k]

# placeholders -- will be set during startup
embedder = None
vector_db = None
# Simple in-memory chat histories keyed by session_id
chat_histories = {}
# Session-scoped contexts
search_contexts = {}
booking_contexts = {}

# -------------------------------
# 3. PDF loader (safe)
# -------------------------------
def load_pdf(file_path: str) -> List[str]:
    docs: List[str] = []
    if not file_path:
        return docs
    if not PyPDF2:
        print("PyPDF2 not installed -- skipping PDF load")
        return docs
    if os.path.exists(file_path) and file_path.endswith(".pdf"):
        try:
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    try:
                        text = page.extract_text()
                    except Exception:
                        text = ""
                    if text:
                        docs.append(text)
        except Exception as e:
            print("Error reading PDF:", e)
    return docs

# -------------------------------
# 4. Authentication Helpers
# -------------------------------
def create_token(customer_id: int, email: str) -> str:
    """Create JWT token for authenticated user"""
    payload = {
        "customer_id": customer_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def _db_path() -> str:
    """Return absolute path to airline_customers.db regardless of CWD."""
    return os.path.join(os.path.dirname(__file__), "airline_customers.db")

def _get_conn():
    """Return a sqlite3 connection ensuring path exists; raise descriptive error."""
    path = _db_path()
    try:
        return sqlite3.connect(path)
    except Exception as e:
        raise RuntimeError(f"Database open failed at {path}: {e}")

def authenticate_user(email: str, password: str, db_path: str = None) -> Optional[dict]:
    db_path = db_path or _db_path()
    """Authenticate user with email and password"""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        cur.execute(
            "SELECT customer_id, name, email, password_hash FROM customers WHERE email = ?",
            (email,)
        )
        user = cur.fetchone()
        
        if not user:
            return None
        
        customer_id, name, email, password_hash = user
        
        # Verify password
        if bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
            return {
                "customer_id": customer_id,
                "name": name,
                "email": email
            }
        return None
    except Exception as e:
        print(f"Authentication error: {e}")
        return None
    finally:
        if "conn" in locals():
            conn.close()

# -------------------------------
# 5. Customer DB helper
# -------------------------------
def get_customer_data(customer_id: int = None, name: str = None, db_path: str = None) -> str:
    db_path = db_path or _db_path()
    """Get customer profile and booking history for airline customers"""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Query by customer_id (preferred for authenticated users)
        if customer_id is not None:
            cur.execute(
                "SELECT customer_id, name, email, phone, passport_number, frequent_flyer_number, nationality, status FROM customers WHERE customer_id = ?",
                (customer_id,)
            )
        # Fallback to name search
        elif name is not None:
            cur.execute(
                "SELECT customer_id, name, email, phone, passport_number, frequent_flyer_number, nationality, status FROM customers WHERE name LIKE ?",
                (f"%{name}%",),
            )
        else:
            return "❌ No customer identifier provided."
        
        customer = cur.fetchone()
        if not customer:
            return "❌ No customer found with that name."

        customer_id, name, email, phone, passport, ff_number, nationality, status = customer

        # Get bookings with flight details
        cur.execute(
            """
            SELECT b.booking_id, b.pnr, f.flight_number, f.airline, f.origin, f.destination, 
                   f.departure_time, f.arrival_time, b.seat_number, b.booking_status, b.total_price, f.flight_type
            FROM bookings b
            JOIN flights f ON b.flight_id = f.flight_id
            WHERE b.customer_id=?
            ORDER BY f.departure_time DESC
            """,
            (customer_id,),
        )
        bookings = cur.fetchall()

        response = [f"✈️ **Welcome, {name}!**\n"]
        response.append(f"📧 Email: {email}")
        response.append(f"📞 Phone: {phone}")
        response.append(f"🛂 Passport: {passport}")
        response.append(f"🎫 Frequent Flyer: {ff_number}")
        response.append(f"🌏 Nationality: {nationality}")
        response.append(f"✅ Account Status: {status}")

        if bookings:
            response.append("\n📋 **Your Booking History:**")
            for b in bookings:
                booking_id, pnr, flight_num, airline, origin, dest, dep_time, arr_time, seat, booking_status, price, flight_type = b
                
                # Format price in Indian Rupees
                price_inr = f"₹{price:,.0f}"
                
                flight_emoji = "🌍" if flight_type == "International" else "✈️"
                status_emoji = "✅" if booking_status == "Confirmed" else "📝" if booking_status == "Completed" else "⏳"
                
                response.append(
                    f"\n{flight_emoji} **Booking #{booking_id}** (PNR: {pnr})\n"
                    f"   {status_emoji} Status: {booking_status}\n"
                    f"   ✈️ {airline} Flight {flight_num}\n"
                    f"   🛫 {origin} → 🛬 {dest}\n"
                    f"   📅 Departure: {dep_time}\n"
                    f"   📅 Arrival: {arr_time}\n"
                    f"   💺 Seat: {seat} | 💰 Price: {price_inr}\n"
                    f"   🌐 Type: {flight_type}"
                )
        else:
            response.append("\n📋 No booking history found.")

        return "\n".join(response)
    except Exception as e:
        return f"⚠️ Database error: {str(e)}"
    finally:
        if "conn" in locals():
            conn.close()

def _extract_city_tokens(text: str) -> dict:
    """Heuristic extractor for origin/destination.
    Supports phrases:
      - 'from X to Y'
      - 'X to Y' (no 'from')
      - just 'to Y' or 'from X' (asks for the other)
      - 'i need to go X' → destination only
      - two city names anywhere in text → first is origin, second is destination
    """
    txt = text.lower().strip()
    cities = [
        "delhi", "del", "mumbai", "bom", "bengaluru", "bangalore", "blr",
        "hyderabad", "hyd", "chennai", "maa", "kolkata", "ccu",
        "dubai", "dxb", "singapore", "sin", "london", "lhr", "new york", "jfk", "pune"
    ]

    import re
    origin = None
    destination = None

    # Pattern 1: from X to Y
    m = re.search(r"from\s+([a-zA-Z ]+?)\s+to\s+([a-zA-Z ]+)", txt)
    if m:
        f1, f2 = m.group(1).strip(), m.group(2).strip()
        origin = next((c for c in cities if c in f1.lower()), None)
        destination = next((c for c in cities if c in f2.lower()), None)
        return {"origin": origin, "destination": destination}

    # Pattern 2: X to Y (no 'from')
    m = re.search(r"([a-zA-Z]+)\s+to\s+([a-zA-Z]+)", txt)
    if m:
        f1, f2 = m.group(1).strip(), m.group(2).strip()
        origin = next((c for c in cities if c == f1.lower() or f1.lower() in c), None)
        destination = next((c for c in cities if c == f2.lower() or f2.lower() in c), None)
        return {"origin": origin, "destination": destination}

    # Pattern 3: "need to go X" or "going to X" → destination only
    m = re.search(r"(?:need to go|going to|go to|visit|fly to|travel to)\s+([a-zA-Z]+)", txt)
    if m:
        f1 = m.group(1).strip().lower()
        destination = next((c for c in cities if c == f1 or f1 in c), None)
        return {"origin": origin, "destination": destination}

    # Pattern 4: only destination 'to Y'
    m = re.search(r"to\s+([a-zA-Z]+)", txt)
    if m:
        f1 = m.group(1).strip().lower()
        destination = next((c for c in cities if c == f1 or f1 in c), None)

    # Pattern 5: only origin 'from X'
    m = re.search(r"from\s+([a-zA-Z]+)", txt)
    if m:
        f1 = m.group(1).strip().lower()
        origin = next((c for c in cities if c == f1 or f1 in c), None)

    # Fallback: find all city mentions in order
    if not origin or not destination:
        occurrences = []
        for c in cities:
            if c in txt:
                idx = txt.find(c)
                occurrences.append((idx, c))
        occurrences.sort(key=lambda x: x[0])
        if len(occurrences) >= 2:
            if not origin and not destination:
                origin = occurrences[0][1]
                destination = occurrences[1][1]
        elif len(occurrences) == 1:
            # If only one city mentioned, treat as destination
            if not destination:
                destination = occurrences[0][1]

    return {"origin": origin, "destination": destination}

def _city_match_sql(column: str, token: str) -> str:
    # Build a LIKE clause for token covering name and code parts present in our data strings
    return f"LOWER({column}) LIKE '%' || ? || '%'"

def _extract_date_tokens(text: str) -> Optional[str]:
    """Extract a simple travel date token like '2025-12-05' or phrases like 'tomorrow', 'today', 'on 5 Dec'. Returns ISO date string if parsed."""
    import re
    from datetime import datetime, timedelta
    t = (text or "").lower()
    # ISO-like date
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if m:
        return m.group(1)
    # on 5 Dec / 05 Dec
    m2 = re.search(r"on\s+(\d{1,2})\s+([a-zA-Z]{3,})", t)
    if m2:
        day = int(m2.group(1))
        mon = m2.group(2)[:3].lower()
        months = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
        if mon in months:
            month_num = months.index(mon) + 1
            year = datetime.now().year
            try:
                return f"{year:04d}-{month_num:02d}-{day:02d}"
            except Exception:
                pass
    # relative
    if "tomorrow" in t:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if "today" in t:
        return datetime.now().strftime("%Y-%m-%d")
    return None

def search_flights_tool(query: str, session_id: Optional[str] = None) -> str:
    """Interactive search: collect origin, destination, date and return concise matches; no flight number required."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        
        # Load existing session context (if any)
        ctx = search_contexts.get(session_id or "default", {})
        
        # Track what we're asking for to correctly assign user's response
        asking_for_origin = ctx.get("destination") and not ctx.get("origin")
        asking_for_dest = ctx.get("origin") and not ctx.get("destination")
        
        extracted = _extract_city_tokens(query or "")
        
        # Smart assignment based on context
        if asking_for_origin and extracted.get("destination"):
            # User was asked for departure city, they provided one city → it's origin
            ctx["origin"] = extracted["destination"]
        elif asking_for_dest and extracted.get("destination"):
            # User was asked for destination, they provided one city → it's destination
            ctx["destination"] = extracted["destination"]
        else:
            # Normal extraction
            if extracted.get("origin"):
                ctx["origin"] = extracted["origin"]
            if extracted.get("destination"):
                ctx["destination"] = extracted["destination"]
        
        dt = _extract_date_tokens(query or "")
        if dt:
            ctx["date"] = dt
        search_contexts[session_id or "default"] = ctx

        # Ask for missing info step-by-step (origin, destination, date)
        if not ctx.get("destination") and not ctx.get("origin"):
            return "🧭 Where are you flying from and to? You can say 'from Delhi to Mumbai'."
        if ctx.get("origin") and not ctx.get("destination"):
            return "🛬 Noted your origin. Which destination city?"
        if ctx.get("destination") and not ctx.get("origin"):
            return "🛫 Got your destination. What's your departure city?"
        if not ctx.get("date"):
            return "📅 What date are you traveling? (e.g., 2025-12-05 or 'tomorrow')"

        # We have origin/destination/date; run filtered query and show concise top results
        origin_token = ctx["origin"]
        dest_token = ctx["destination"]
        date_token = ctx["date"]
        sql = (
            "SELECT flight_id, flight_number, airline, origin, destination, departure_time, price, flight_type "
            "FROM flights WHERE available_seats > 0 AND "
            + _city_match_sql("origin", "?") + " AND " + _city_match_sql("destination", "?") + " "
            "ORDER BY datetime(departure_time) LIMIT 5"
        )
        # For parameter order use tokens directly (lowercase) and filter by date (same day)
        cur.execute(
            "SELECT flight_id, flight_number, airline, origin, destination, departure_time, price, flight_type "
            "FROM flights WHERE available_seats > 0 AND LOWER(origin) LIKE '%' || ? || '%' AND LOWER(destination) LIKE '%' || ? || '%' "
            "AND substr(departure_time,1,10)=? "
            "ORDER BY datetime(departure_time) LIMIT 5",
            (origin_token, dest_token, date_token),
        )
        flights = cur.fetchall()
        if not flights:
            return "❌ No flights match that route/date. Try a different date or cities."

        lines = ["✈️ Matching flights (top results):\n"]
        for fid, num, airline, origin, dest, dep, price, ftype in flights:
            price_inr = f"₹{price:,.0f}"
            lines.append(f"• {airline} {num} — {origin} → {dest} — Dep: {dep} — Fare: {price_inr}")
        lines.append("\nTo book, just say: 'book this' or 'book first one'.")

        # Clear context after presenting results to avoid stale constraints
        search_contexts.pop(session_id or "default", None)
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error searching flights: {str(e)}"
    finally:
        if "conn" in locals():
            conn.close()

def book_flight_tool(query: str, session_id: Optional[str] = None, customer_id: Optional[int] = None) -> str:
    """Booking without flight number: collect origin, destination, date; show matches; confirm seat and payment."""
    if customer_id is None:
        return "❌ You must be logged in to book flights."

    import re
    from datetime import datetime
    sid = session_id or "default"
    ctx = booking_contexts.get(sid, {"stage": "collect"})
    txt = (query or "").lower()

    # Stage: collect origin/destination/date
    if ctx["stage"] == "collect":
        # Track what we're asking for to correctly assign user's response
        asking_for_origin = ctx.get("destination") and not ctx.get("origin")
        asking_for_dest = ctx.get("origin") and not ctx.get("destination")
        
        cities = _extract_city_tokens(txt)
        
        # Smart assignment based on context
        if asking_for_origin and cities.get("destination"):
            # User was asked for departure city, they provided one city → it's origin
            ctx["origin"] = cities["destination"]
        elif asking_for_dest and cities.get("destination"):
            # User was asked for destination, they provided one city → it's destination
            ctx["destination"] = cities["destination"]
        else:
            # Normal extraction
            if cities.get("origin"):
                ctx["origin"] = cities["origin"]
            if cities.get("destination"):
                ctx["destination"] = cities["destination"]
        
        dt = _extract_date_tokens(txt)
        if dt:
            ctx["date"] = dt

        booking_contexts[sid] = ctx

        # Check what's missing and prompt step-by-step
        missing_origin = not ctx.get("origin")
        missing_dest = not ctx.get("destination")
        missing_date = not ctx.get("date")

        if missing_origin and missing_dest:
            return "🧭 To book, tell me where you're flying from and to."
        if not missing_dest and missing_origin:
            return "🛫 Got your destination. What's your departure city?"
        if not missing_origin and missing_dest:
            return "🛬 Noted your origin. Which destination city?"
        if missing_date:
            return "📅 What date are you traveling? (e.g., 2025-12-05 or 'tomorrow')"

        # Have all details → query flights and present top options
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT flight_id, flight_number, airline, origin, destination, departure_time, price, flight_type "
                "FROM flights WHERE available_seats > 0 AND LOWER(origin) LIKE '%' || ? || '%' AND LOWER(destination) LIKE '%' || ? || '%' "
                "AND substr(departure_time,1,10)=? ORDER BY datetime(departure_time) LIMIT 5",
                (ctx["origin"], ctx["destination"], ctx["date"]),
            )
            flights = cur.fetchall()
            if not flights:
                return "❌ No flights available for that route/date. Try another date."
            ctx["options"] = [(fid, num, airline, origin, dest, dep, price) for fid, num, airline, origin, dest, dep, price, _ in flights]
            ctx["stage"] = "choose"
            booking_contexts[sid] = ctx
            lines = ["✈️ Available flights:\n"]
            for i, (_, num, airline, origin, dest, dep, price) in enumerate(ctx["options"], start=1):
                lines.append(f"{i}. {airline} {num} — {origin} → {dest} — Dep: {dep} — Fare: ₹{price:,.0f}")
            lines.append("\nReply 'book first', 'book second', or 'book this'.")
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ Booking search failed: {str(e)}"
        finally:
            if "conn" in locals():
                conn.close()

    # Stage: choose flight option
    if ctx["stage"] == "choose":
        idx = None
        if "first" in txt:
            idx = 1
        elif "second" in txt:
            idx = 2
        else:
            m = re.search(r"book\s+(\d)", txt)
            if m:
                idx = int(m.group(1))
        if idx is None and ("book this" in txt or "book" in txt):
            idx = 1
        if not idx or idx < 1 or idx > len(ctx.get("options", [])):
            return "Please choose which option to book (e.g., 'book first')."
        choice = ctx["options"][idx-1]
        ctx["chosen"] = choice  # (fid, num, airline, origin, dest, dep, price)
        ctx["stage"] = "seat"
        booking_contexts[sid] = ctx
        return "💺 What seat would you like (e.g., 12A)?"

    # Stage: get seat
    if ctx["stage"] == "seat":
        m = re.search(r"\b(\d{1,2}[A-F])\b", txt)
        if not m:
            return "Please provide a seat like 12A, 15C, etc."
        ctx["seat"] = m.group(1).upper()
        ctx["stage"] = "payment"
        booking_contexts[sid] = ctx
        return "💳 Great. Which payment method? (UPI / Credit Card / Debit Card / Net Banking)"

    # Stage: payment and confirm
    if ctx["stage"] == "payment":
        method_map = {
            "upi": "UPI",
            "credit": "Credit Card",
            "debit": "Debit Card",
            "net": "Net Banking",
            "bank": "Net Banking",
        }
        pm = next((v for k, v in method_map.items() if k in txt), None)
        if not pm:
            return "Choose a payment method: UPI, Credit Card, Debit Card, or Net Banking."
        ctx["payment_method"] = pm

        # Create booking in DB for the chosen flight
        try:
            conn = _get_conn()
            cur = conn.cursor()

            if not ctx.get("chosen"):
                return "❌ No flight selected. Please choose an option to book."
            flight_id, flight_num, airline, origin, dest, dep, price = ctx["chosen"]

            booking_date = datetime.now().strftime("%Y-%m-%d")
            pnr = f"PNR{abs(hash(sid+str(flight_id))) % 1000000:06d}"

            cur.execute(
                "INSERT INTO bookings (customer_id, flight_id, booking_date, seat_number, booking_status, total_price, pnr) "
                "VALUES (?, ?, ?, ?, 'Confirmed', ?, ?)",
                (customer_id, flight_id, booking_date, ctx["seat"], price, pnr),
            )
            booking_id = cur.lastrowid

            # Decrease available seats
            cur.execute("UPDATE flights SET available_seats = available_seats - 1 WHERE flight_id=? AND available_seats>0", (flight_id,))

            payment_date = booking_date
            cur.execute(
                "INSERT INTO payments (booking_id, amount, payment_method, payment_date, payment_status) VALUES (?, ?, ?, ?, 'Completed')",
                (booking_id, price, pm, payment_date),
            )
            conn.commit()

            price_inr = f"₹{price:,.0f}"
            booking_contexts.pop(sid, None)
            return (
                "✅ Booking Confirmed\n"
                f"Booking ID: {booking_id} | PNR: {pnr}\n"
                f"Flight: {airline} {flight_num} | {origin} → {dest} | Dep: {dep}\n"
                f"Seat: {ctx['seat']} | Payment: {pm} | Fare: {price_inr}\n"
                "Have a great trip!"
            )
        except Exception as e:
            return f"⚠️ Booking failed: {str(e)}"
        finally:
            if "conn" in locals():
                conn.close()

    # Fallback restart
    booking_contexts[sid] = {"stage": "start"}
    return "Let's start your booking. Tell me the flight number (e.g., AI101)."

def check_booking_status_tool(query: str, customer_id: Optional[int] = None) -> str:
    """Check booking status by booking ID or show all customer bookings"""
    if customer_id is None:
        return "❌ You must be logged in to check bookings."
    
    try:
        conn = _get_conn()
        cur = conn.cursor()
        
        # Try to extract booking ID from query
        import re
        booking_match = re.search(r'\b(\d+)\b', query)
        
        if booking_match:
            # Get specific booking
            booking_id = int(booking_match.group(1))
            cur.execute("""
                SELECT b.booking_id, b.pnr, c.name, f.flight_number, f.airline, f.origin, f.destination,
                       f.departure_time, f.arrival_time, b.seat_number, b.booking_status, b.total_price, 
                       f.flight_type, f.available_seats
                FROM bookings b
                JOIN customers c ON b.customer_id = c.customer_id
                JOIN flights f ON b.flight_id = f.flight_id
                WHERE b.booking_id = ? AND b.customer_id = ?
            """, (booking_id, customer_id))
            
            booking = cur.fetchone()
            
            if booking:
                bid, pnr, name, flight_num, airline, origin, dest, dep, arr, seat, status, price, ftype, avail_seats = booking
                price_inr = f"₹{price:,.0f}"
                flight_emoji = "🌍" if ftype == "International" else "✈️"
                status_emoji = "✅" if status == "Confirmed" else "🎫" if status == "Completed" else "⏳"
                
                return (
                    f"{flight_emoji} **Booking Details** (ID: {bid})\n\n"
                    f"📝 PNR: {pnr}\n"
                    f"👤 Passenger: {name}\n"
                    f"{status_emoji} Status: {status}\n\n"
                    f"✈️ **Flight Information**\n"
                    f"   Airline: {airline}\n"
                    f"   Flight Number: {flight_num}\n"
                    f"   Type: {ftype}\n\n"
                    f"📍 **Route**\n"
                    f"   From: {origin}\n"
                    f"   To: {dest}\n\n"
                    f"⏱️ **Schedule**\n"
                    f"   Departure: {dep}\n"
                    f"   Arrival: {arr}\n\n"
                    f"💺 **Seat Assignment**\n"
                    f"   Seat: {seat}\n\n"
                    f"💰 **Fare**\n"
                    f"   Total Price: {price_inr}\n"
                    f"   Seats Available on Flight: {avail_seats}"
                )
        
        # If no booking ID provided, show all bookings
        cur.execute("""
            SELECT b.booking_id, b.pnr, f.flight_number, f.airline, f.origin, f.destination,
                   f.departure_time, b.seat_number, b.booking_status, b.total_price, f.flight_type
            FROM bookings b
            JOIN flights f ON b.flight_id = f.flight_id
            WHERE b.customer_id = ?
            ORDER BY f.departure_time DESC
        """, (customer_id,))
        
        bookings = cur.fetchall()
        if not bookings:
            return "📋 You have no bookings yet."
        
        response = [f"📋 **Your Bookings ({len(bookings)} total)**\n"]
        for b in bookings:
            bid, pnr, flight_num, airline, origin, dest, dep, seat, status, price, ftype = b
            price_inr = f"₹{price:,.0f}"
            flight_emoji = "🌍" if ftype == "International" else "✈️"
            status_emoji = "✅" if status == "Confirmed" else "🎫" if status == "Completed" else "⏳"
            response.append(
                f"{flight_emoji} Booking #{bid} (PNR: {pnr}) {status_emoji}\n"
                f"   {airline} {flight_num}\n"
                f"   {origin} → {dest}\n"
                f"   Dep: {dep} | Seat: {seat}\n"
                f"   Price: {price_inr}\n"
            )
        
        return "\n".join(response)
    except Exception as e:
        return f"⚠️ Error checking booking: {str(e)}"
    finally:
        if "conn" in locals():
            conn.close()

def manage_booking_tool(query: str) -> str:
    """Help with booking modifications (cancellation, changes)"""
    return (
        "✈️ Booking Management Options:\n\n"
        "I can help you with:\n"
        "• Cancel your booking\n"
        "• Change your seat\n"
        "• Modify travel dates\n"
        "• Add extra baggage\n"
        "• Special meal requests\n\n"
        "Please let me know your booking ID and what you'd like to change!"
    )

def flight_details_tool(query: str, customer_id: Optional[int] = None) -> str:
    """Get detailed information about a specific flight"""
    try:
        import re
        conn = _get_conn()
        cur = conn.cursor()
        
        # Try to extract flight number from query
        flight_match = re.search(r'\b([a-z]{2}\d{1,4})\b', query, re.IGNORECASE)
        
        if not flight_match:
            return "✈️ Please provide a flight number (e.g., 'Details of flight AI101')."
        
        flight_num = flight_match.group(1).upper()
        
        cur.execute("""
            SELECT flight_id, flight_number, airline, origin, destination, departure_time, arrival_time,
                   price, available_seats, aircraft_type, flight_type
            FROM flights
            WHERE flight_number = ?
        """, (flight_num,))
        
        flight = cur.fetchone()
        if not flight:
            return f"❌ Flight {flight_num} not found in our system."
        
        fid, fnum, airline, origin, dest, dep, arr, price, avail_seats, aircraft, ftype = flight
        
        # Calculate duration (simplified)
        from datetime import datetime
        try:
            dep_dt = datetime.strptime(dep.split()[1], "%H:%M")
            arr_dt = datetime.strptime(arr.split()[1], "%H:%M")
            duration = arr_dt - dep_dt
            if duration.total_seconds() < 0:
                duration = timedelta(hours=24) + duration
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            duration_str = f"{hours}h {minutes}m"
        except:
            duration_str = "N/A"
        
        price_inr = f"₹{price:,.0f}"
        flight_emoji = "🌍" if ftype == "International" else "✈️"
        
        return (
            f"{flight_emoji} **Flight Details**\n\n"
            f"📌 **Flight Identification**\n"
            f"   Flight Number: {fnum}\n"
            f"   Airline: {airline}\n"
            f"   Aircraft: {aircraft}\n"
            f"   Type: {ftype}\n\n"
            f"📍 **Route Information**\n"
            f"   Departure: {origin}\n"
            f"   Destination: {dest}\n\n"
            f"⏱️ **Schedule**\n"
            f"   Departure: {dep}\n"
            f"   Arrival: {arr}\n"
            f"   Duration: {duration_str}\n\n"
            f"💺 **Seat & Capacity**\n"
            f"   Available Seats: {avail_seats}\n\n"
            f"💰 **Pricing**\n"
            f"   Fare (per seat): {price_inr}\n\n"
            f"✅ **Amenities Included:**\n"
            f"   • Complimentary meal service\n"
            f"   • 23kg baggage allowance\n"
            f"   • In-flight entertainment\n"
            f"   • WiFi (International flights)\n\n"
            f"ℹ️ To book this flight, say 'Book from {origin} to {dest}' or provide your travel dates."
        )
    except Exception as e:
        return f"⚠️ Error retrieving flight details: {str(e)}"
    finally:
        if "conn" in locals():
            conn.close()

# def manage_booking_tool(query: str) -> str:
#     """Help with booking modifications (cancellation, changes)"""
#     return (
#         "✈️ Booking Management Options:\n\n"
#         "I can help you with:\n"
#         "• Cancel your booking\n"
#         "• Change your seat\n"
#         "• Modify travel dates\n"
#         "• Add extra baggage\n"
#         "• Special meal requests\n\n"
#         "Please let me know your booking ID and what you'd like to change!"
#     )

# -------------------------------
# 5. Tools (unchanged behaviour, but robust)
# -------------------------------
def rag_tool(query: str) -> str:
    """Provide comprehensive airline information for any query"""
    q = (query or "").lower()
    
    # Baggage related queries
    if any(w in q for w in ["baggage", "luggage", "bag", "carry", "check-in", "weight", "kg"]):
        return (
            "🧳 **SkyLine Airways Baggage Policy**\n\n"
            "**Domestic Flights:**\n"
            "• Carry-on: 1 bag (max 10 kg, 55x40x20 cm)\n"
            "• Checked baggage: 1 bag (max 23 kg)\n"
            "• Extra baggage: ₹500 per kg\n\n"
            "**International Flights:**\n"
            "• Carry-on: 1 bag (max 10 kg)\n"
            "• Checked baggage: 2 bags (max 32 kg each)\n"
            "• Extra baggage: ₹800 per kg\n\n"
            "**Prohibited Items:** Flammables, sharp objects, liquids >100ml in carry-on\n\n"
            "Need help with anything else?"
        )
    
    # Check-in related queries
    if any(w in q for w in ["check-in", "checkin", "web check", "online check", "airport check"]):
        return (
            "✅ **Check-in Information**\n\n"
            "**Online/Web Check-in:**\n"
            "• Opens: 48 hours before departure\n"
            "• Closes: 2 hours before departure\n"
            "• Get boarding pass on email/app\n\n"
            "**Airport Check-in:**\n"
            "• Domestic: Counter opens 3 hours before, closes 45 mins before\n"
            "• International: Counter opens 4 hours before, closes 1 hour before\n\n"
            "**Self-service Kiosks:** Available at major airports\n\n"
            "Would you like help with anything else?"
        )
    
    # Cancellation/refund queries
    if any(w in q for w in ["cancel", "refund", "cancellation", "money back"]):
        return (
            "💰 **Cancellation & Refund Policy**\n\n"
            "**Free Cancellation:**\n"
            "• Within 24 hours of booking: Full refund\n\n"
            "**Standard Cancellation Fees:**\n"
            "• More than 7 days before: 10% fee\n"
            "• 3-7 days before: 25% fee\n"
            "• 24-72 hours before: 50% fee\n"
            "• Less than 24 hours: No refund (credit only)\n\n"
            "**Refund Processing:**\n"
            "• Credit/Debit Card: 5-7 business days\n"
            "• UPI/Net Banking: 3-5 business days\n\n"
            "To cancel a booking, say 'cancel my booking' or provide your PNR."
        )
    
    # Meal queries
    if any(w in q for w in ["meal", "food", "vegetarian", "veg", "non-veg", "eat", "dinner", "lunch", "breakfast"]):
        return (
            "🍽️ **In-Flight Meals**\n\n"
            "**Complimentary Meals:**\n"
            "• Domestic flights > 2 hours: Light snacks\n"
            "• International flights: Full meal service\n\n"
            "**Special Meal Options (pre-order 24hrs before):**\n"
            "• Vegetarian (Hindu/Jain)\n"
            "• Non-Vegetarian\n"
            "• Vegan\n"
            "• Diabetic-friendly\n"
            "• Child meals\n"
            "• Kosher/Halal\n\n"
            "**Buy on Board:** Snacks, beverages available for purchase on domestic flights.\n\n"
            "Would you like to pre-order a special meal?"
        )
    
    # Seat selection queries
    if any(w in q for w in ["seat", "window", "aisle", "legroom", "extra leg"]):
        return (
            "💺 **Seat Selection**\n\n"
            "**Free Seats:** Standard middle seats\n\n"
            "**Preferred Seats (₹300-500):**\n"
            "• Window seats\n"
            "• Aisle seats\n"
            "• Front rows\n\n"
            "**Extra Legroom (₹800-1500):**\n"
            "• Exit row seats\n"
            "• Bulkhead seats\n\n"
            "**Business Class:** Premium seats with extra recline\n\n"
            "To select a seat, say 'I want seat 12A' during booking."
        )
    
    # WiFi/entertainment queries
    if any(w in q for w in ["wifi", "internet", "entertainment", "movie", "music"]):
        return (
            "📱 **In-Flight Entertainment & WiFi**\n\n"
            "**WiFi (International Flights):**\n"
            "• Complimentary messaging\n"
            "• Browse package: ₹500/flight\n"
            "• Streaming package: ₹1000/flight\n\n"
            "**Entertainment System:**\n"
            "• Seatback screens on Boeing 787 & Airbus A380\n"
            "• Movies, TV shows, music, games\n"
            "• Kids entertainment section\n\n"
            "**Domestic Flights:** Stream to your device via onboard WiFi (free)"
        )
    
    # Visa/passport queries
    if any(w in q for w in ["visa", "passport", "document", "id proof", "identity"]):
        return (
            "🛂 **Travel Documents Required**\n\n"
            "**Domestic Flights:**\n"
            "• Valid Photo ID (Aadhaar, PAN, Passport, Driving License, Voter ID)\n\n"
            "**International Flights:**\n"
            "• Valid Passport (6+ months validity)\n"
            "• Valid Visa for destination country\n"
            "• Return ticket proof (some countries)\n\n"
            "**Important:** Carry original documents. Name must match booking exactly.\n\n"
            "Need visa information for a specific country? Just ask!"
        )
    
    # Delay/compensation queries
    if any(w in q for w in ["delay", "late", "compensation", "waiting"]):
        return (
            "⏰ **Flight Delay Compensation**\n\n"
            "**Delay < 2 hours:** Refreshments provided\n"
            "**Delay 2-4 hours:** Meal vouchers\n"
            "**Delay > 4 hours:** Hotel accommodation (if required)\n"
            "**Delay > 6 hours:** Option to cancel with full refund\n\n"
            "**Compensation for Cancellation by Airline:**\n"
            "• Full refund OR\n"
            "• Free rebooking on next available flight\n"
            "• ₹5000 travel voucher\n\n"
            "Check flight status by saying 'status of flight AI101'"
        )
    
    # Pet travel queries
    if any(w in q for w in ["pet", "dog", "cat", "animal"]):
        return (
            "🐕 **Pet Travel Policy**\n\n"
            "**In-Cabin (small pets < 7 kg):**\n"
            "• Carrier must fit under seat\n"
            "• Booking required 48hrs in advance\n"
            "• Fee: ₹3000 (Domestic), ₹8000 (International)\n\n"
            "**Cargo Hold (larger pets):**\n"
            "• IATA-approved crate required\n"
            "• Health certificate from vet\n"
            "• Fee based on weight\n\n"
            "**Not Allowed:** Snub-nosed breeds, aggressive animals\n\n"
            "Contact us 48 hours before to arrange pet travel."
        )
    
    # Infant/child queries
    if any(w in q for w in ["infant", "baby", "child", "kid", "minor", "unaccompanied"]):
        return (
            "👶 **Traveling with Children**\n\n"
            "**Infants (0-2 years):**\n"
            "• Sit on parent's lap (10% of adult fare)\n"
            "• Bassinet available on long flights (pre-book)\n"
            "• Carry baby food, formula freely\n\n"
            "**Children (2-12 years):**\n"
            "• Own seat required (75% of adult fare)\n"
            "• Kids meal available\n\n"
            "**Unaccompanied Minors (5-12 years):**\n"
            "• ₹2500 service fee\n"
            "• Staff escort throughout journey\n"
            "• Guardian must complete forms at airport\n\n"
            "Need to book for a child? Just tell me the travel details!"
        )
    
    # Wheelchair/special assistance
    if any(w in q for w in ["wheelchair", "disability", "special assistance", "medical", "oxygen"]):
        return (
            "♿ **Special Assistance Services**\n\n"
            "**Wheelchair Service (Free):**\n"
            "• Request during booking or 48hrs before\n"
            "• Airport staff will assist throughout\n\n"
            "**Medical Equipment:**\n"
            "• Portable oxygen concentrators: Allowed (pre-approval needed)\n"
            "• Mobility aids: Checked free of charge\n\n"
            "**Hearing/Vision Impaired:**\n"
            "• Priority boarding\n"
            "• Safety briefing assistance\n\n"
            "**Traveling with Medical Condition:**\n"
            "• Doctor's fit-to-fly certificate may be required\n\n"
            "Contact us 48 hours before for special assistance."
        )
    
    # Default comprehensive help message
    return (
        "✈️ **SkyLine Airways - How Can I Help?**\n\n"
        "I can assist you with:\n\n"
        "🔍 **Search & Book Flights**\n"
        "   Say: 'Find flights from Delhi to Mumbai'\n\n"
        "📋 **Check Your Bookings**\n"
        "   Say: 'Show my bookings' or 'Check booking status'\n\n"
        "👤 **View Your Profile**\n"
        "   Say: 'Show my profile' or 'My account details'\n\n"
        "✈️ **Flight Information**\n"
        "   Say: 'Details of flight AI101'\n\n"
        "📝 **Policies & Information**\n"
        "   Ask about: Baggage, check-in, cancellation, meals, seats, WiFi, visa, pets, children, special assistance\n\n"
        "🎫 **Sample Booking Query:**\n"
        "   'Book a flight from Delhi to Mumbai on 2025-12-20'\n\n"
        "What would you like to know?"
    )

def complaint_tool(query: str) -> str:
    """Register customer complaints"""
    return (
        f"📩 Complaint Registered\n\n"
        f"Thank you for bringing this to our attention.\n"
        f"Your complaint has been logged and our customer service team will review it.\n"
        f"You should receive a response within 24-48 hours.\n\n"
        f"Reference: COMP-{abs(hash(query)) % 100000}"
    )

def flight_details_tool(query: str) -> str:
    """Get detailed information about a specific flight"""
    try:
        import re
        conn = _get_conn()
        cur = conn.cursor()
        
        # Try to extract flight number
        flight_match = re.search(r'([A-Z]{2}\d+)', query.upper())
        if not flight_match:
            return "❌ Please provide a flight number (e.g., 'SG123')."
        
        flight_num = flight_match.group(1)
        cur.execute(
            """
            SELECT flight_id, flight_number, airline, origin, destination, departure_time, 
                   arrival_time, price, available_seats, aircraft_type, flight_type, duration
            FROM flights WHERE UPPER(flight_number) = ?
            """,
            (flight_num,)
        )
        
        flight = cur.fetchone()
        if not flight:
            return f"❌ Flight {flight_num} not found."
        
        fid, fnum, airline, origin, dest, dep, arr, price, seats, aircraft, ftype, duration = flight
        price_inr = f"₹{price:,.0f}"
        flight_emoji = "🌍" if ftype == "International" else "✈️"
        
        return (
            f"{flight_emoji} **Flight Details: {airline} {fnum}**\n\n"
            f"📍 **Route**\n"
            f"   From: {origin}\n"
            f"   To: {dest}\n\n"
            f"⏱️ **Schedule**\n"
            f"   Departure: {dep}\n"
            f"   Arrival: {arr}\n"
            f"   Duration: {duration}\n\n"
            f"✈️ **Aircraft**\n"
            f"   Type: {aircraft}\n"
            f"   Class: {ftype}\n\n"
            f"💺 **Availability**\n"
            f"   Seats Available: {seats}\n\n"
            f"💰 **Fare**\n"
            f"   Price: {price_inr}\n\n"
            f"📝 To book this flight, say 'book this flight' or start a new search."
        )
    except Exception as e:
        return f"⚠️ Error fetching flight details: {str(e)}"
    finally:
        if "conn" in locals():
            conn.close()

def customer_info_tool(query: str, customer_id: Optional[int] = None) -> str:
    """Get customer information, booking history, and specific details"""
    if customer_id is None:
        return "❌ You must be logged in to view your information."
    
    q = (query or "").lower()

    try:
        conn = _get_conn()
        cur = conn.cursor()
        
        # Get authenticated user
        cur.execute(
            "SELECT customer_id, name, email, phone, passport_number, frequent_flyer_number, nationality, status FROM customers WHERE customer_id = ?", 
            (customer_id,)
        )
        row = cur.fetchone()
        if not row:
            return "❌ Customer not found."
        cid, name, email, phone, passport, ff_number, nationality, status = row

        # If user asks about previous/last flight
        if any(k in q for k in ["previous flight", "last flight", "past flight", "earlier flight"]):
            cur.execute(
                """
                SELECT b.booking_id, b.pnr, f.airline, f.flight_number, f.origin, f.destination,
                       f.departure_time, f.arrival_time, b.seat_number, b.total_price, f.flight_type
                FROM bookings b
                JOIN flights f ON b.flight_id = f.flight_id
                WHERE b.customer_id=? AND (b.booking_status='Completed' OR b.booking_status='Confirmed')
                ORDER BY f.departure_time DESC
                LIMIT 1
                """,
                (customer_id,),
            )
            booking = cur.fetchone()
            if not booking:
                return "📋 No previous flight found."

            bid, pnr, airline, flight_num, origin, dest, dep, arr, seat, price, ftype = booking
            price_inr = f"₹{price:,.0f}"
            flight_emoji = "🌍" if ftype == "International" else "✈️"

            return (
                f"{flight_emoji} **Previous Flight Summary**\n\n"
                f"👤 Passenger: {name}\n"
                f"📝 PNR: {pnr}\n"
                f"🎫 Booking ID: {bid}\n\n"
                f"✈️ **Flight Info**\n"
                f"   Airline: {airline}\n"
                f"   Flight: {flight_num}\n"
                f"   Type: {ftype}\n\n"
                f"📍 **Route**\n"
                f"   {origin} → {dest}\n\n"
                f"⏱️ **Schedule**\n"
                f"   Departure: {dep}\n"
                f"   Arrival: {arr}\n\n"
                f"💺 Seat: {seat}\n"
                f"💰 Fare: {price_inr}"
            )
        
        # If user asks about profile/account details
        if any(word in q for word in ["account", "profile", "my details", "details", "information"]):
            return (
                f"✈️ **Your Profile - {name}**\n\n"
                f"📧 Email: {email}\n"
                f"📞 Phone: {phone}\n"
                f"🛂 Passport: {passport}\n"
                f"🎫 Frequent Flyer #: {ff_number}\n"
                f"🌏 Nationality: {nationality}\n"
                f"✅ Account Status: {status}\n"
                f"\nFor booking details, ask 'show my bookings' or 'check booking [ID]'"
            )
        
        # If user asks about bookings or history
        if any(word in q for word in ["bookings", "history", "trips", "travels", "my flights"]):
            cur.execute(
                """
                SELECT b.booking_id, b.pnr, f.flight_number, f.airline, f.origin, f.destination,
                       f.departure_time, f.arrival_time, b.seat_number, b.booking_status, b.total_price, f.flight_type
                FROM bookings b
                JOIN flights f ON b.flight_id = f.flight_id
                WHERE b.customer_id=?
                ORDER BY f.departure_time DESC
                """,
                (customer_id,),
            )
            bookings = cur.fetchall()
            if not bookings:
                return "📋 No bookings found. Start by searching and booking a flight!"
            
            response = [f"📋 **Your Booking History ({len(bookings)} bookings)**\n"]
            for b in bookings:
                bid, pnr, flight_num, airline, origin, dest, dep_time, arr_time, seat, booking_status, price, ftype = b
                price_inr = f"₹{price:,.0f}"
                flight_emoji = "🌍" if ftype == "International" else "✈️"
                status_emoji = "✅" if booking_status == "Confirmed" else "🎫" if booking_status == "Completed" else "⏳"
                
                response.append(
                    f"\n{flight_emoji} **Booking #{bid}** (PNR: {pnr}) {status_emoji}\n"
                    f"   {airline} {flight_num}\n"
                    f"   {origin} → {dest}\n"
                    f"   Departure: {dep_time}\n"
                    f"   Arrival: {arr_time}\n"
                    f"   Seat: {seat} | Fare: {price_inr}"
                )
            
            return "\n".join(response)
        
        # Default: show full profile
        return get_customer_data(customer_id=customer_id)
        
    except Exception as e:
        return f"⚠️ Database error: {str(e)}"
    finally:
        if "conn" in locals():
            conn.close()

# -------------------------------
# 6. Router Agent (OpenAI call) - safe version
# -------------------------------
def pick_tool_with_agent(user_input: str) -> dict:
    """
    Returns a dict like {"tool": "<tool>"}.
    If OpenAI client is unavailable or fails, fallback to a simple keyword-based router.
    """
    system_prompt = """
    You are a routing agent for an AIRLINE customer service chatbot.
    Rules:
    1. If small talk/greeting (hi, hello, how are you) → {"tool": "none"}.
    2. Otherwise, pick ONE tool based on intent:
       - search_flights: User wants to search/find/see available flights OR mentions city names with travel intent
       - book_flight: User wants to book/purchase/reserve a ticket OR says "book from X to Y"
       - check_booking: User wants to check/view booking status or details
       - manage_booking: User wants to cancel/modify/change a booking
       - customer_info: User asks about their profile, account, or previous bookings
       - complaint: User has a complaint or issue to report
       - rag: General questions about policies, baggage, etc.
    
    IMPORTANT: If user mentions specific cities or routes (Delhi, Mumbai, Pune, etc.) treat as search_flights or book_flight intent.
    JSON ONLY, format: {"tool": "<tool>"}
    """

    # Quick keyword fallback (used if OpenAI client not available)
    def fallback_rules(inp: str) -> dict:
        txt = inp.lower()
        if any(g in txt for g in ["hi", "hello", "hey", "how are you", "good morning", "good evening"]):
            return {"tool": "none"}
        # Flight search triggers - match city names and search intent
        if any(w in txt for w in ["search", "find", "available", "flights", "show me", "delhi", "mumbai", "pune", "bangalore", "chennai", "hyderabad", "kolkata", "dubai", "singapore", "london"]):
            if any(w in txt for w in ["from", "to", "flight"]):
                return {"tool": "search_flights"}
        # Booking triggers
        if any(w in txt for w in ["book", "reserve", "purchase", "buy ticket", "i want to book", "need to book"]):
            return {"tool": "book_flight"}
        if any(w in txt for w in ["check booking", "booking status", "my booking", "booking id"]):
            return {"tool": "check_booking"}
        if any(w in txt for w in ["cancel", "modify", "change", "reschedule"]):
            return {"tool": "manage_booking"}
        if any(w in txt for w in ["my account", "my profile", "my bookings", "my trips", "previous"]):
            return {"tool": "customer_info"}
        if any(w in txt for w in ["complaint", "complain", "issue", "problem"]):
            return {"tool": "complaint"}
        return {"tool": "rag"}

    if client is None:
        return fallback_rules(user_input)

    # Try OpenAI routing; be defensive about errors and parsing
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=0,
        )
        content = ""
        try:
            content = resp.choices[0].message.content.strip()
        except Exception:
            # defensive fallback
            return fallback_rules(user_input)
        # Try to parse JSON from the model output
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "tool" in parsed:
                return parsed
            else:
                return fallback_rules(user_input)
        except Exception:
            # Sometimes model replies with backticks or extra text — try to extract a JSON substring
            try:
                start = content.index("{")
                end = content.rindex("}") + 1
                snippet = content[start:end]
                parsed = json.loads(snippet)
                if isinstance(parsed, dict) and "tool" in parsed:
                    return parsed
            except Exception:
                pass
            return fallback_rules(user_input)
    except Exception:
        return fallback_rules(user_input)

def tool_picker(user_input: str, session_id: Optional[str] = None, customer_id: Optional[int] = None, customer_name: Optional[str] = None) -> str:
    """Main agent that uses OpenAI to understand customer intent and respond appropriately"""
    
    user_lower = user_input.lower()
    
    # FORCE tool execution for key intents - bypass LLM for these
    # Check for city names and booking/search keywords
    cities = ["delhi", "mumbai", "pune", "bangalore", "bengaluru", "chennai", "hyderabad", "kolkata", "dubai", "singapore", "london", "new york", "jfk", "bom", "del", "blr", "hyd", "maa", "ccu", "dxb", "sin", "lhr"]
    has_city = any(city in user_lower for city in cities)
    has_route = ("from" in user_lower and "to" in user_lower) or (" to " in user_lower)
    
    # Flight search keywords - EXPANDED
    search_keywords = ["search", "find", "show", "available", "flights", "flight", "looking for", "want to fly", "travel", "traveling", "go to", "going to", "fly to", "fly from"]
    has_search_intent = any(kw in user_lower for kw in search_keywords)
    
    # Detect detail/info queries
    detail_keywords = ["details of flight", "tell me about flight", "flight information", "about flight", "show flight", "flight details"]
    booking_info_keywords = ["check booking", "booking status", "my booking", "booking details", "pnr", "reservation status"]
    profile_keywords = ["my profile", "my account", "my details", "my bookings", "booking history", "travel history"]
    
    # Force flight_details_tool
    if any(kw in user_lower for kw in detail_keywords):
        return execute_tool("flight_details", user_input, session_id=session_id, customer_id=customer_id)
    
    # Force check_booking tool
    if any(kw in user_lower for kw in booking_info_keywords):
        return execute_tool("check_booking", user_input, session_id=session_id, customer_id=customer_id)
    
    # Force customer_info tool
    if any(kw in user_lower for kw in profile_keywords):
        return execute_tool("customer_info", user_input, session_id=session_id, customer_id=customer_id)
    
    # Force search_flights tool - PRIORITY: if city mentioned with search intent OR route pattern
    if (has_city and has_search_intent) or has_route or (has_city and not any(w in user_lower for w in ["book", "reserve", "purchase"])):
        return execute_tool("search_flights", user_input, session_id=session_id, customer_id=customer_id)
    
    # Force book_flight tool
    if (has_city or has_route) and any(w in user_lower for w in ["book", "reserve", "purchase", "i want to book", "need to book"]):
        return execute_tool("book_flight", user_input, session_id=session_id, customer_id=customer_id)
    
    # If OpenAI is not available, use basic routing
    if client is None:
        decision = pick_tool_with_agent(user_input)
        tool = decision.get("tool", "rag")
        return execute_tool(tool, user_input, session_id=session_id, customer_id=customer_id)
    
    # Use OpenAI to create an intelligent agent with tool access
    try:
        # First, determine which tool to use (if any) using the routing agent
        decision = pick_tool_with_agent(user_input)
        tool = decision.get("tool", "rag")
        
        # If a specific airline tool is needed, execute it directly
        if tool in ["search_flights", "book_flight", "check_booking", "manage_booking", "customer_info", "complaint"]:
            return execute_tool(tool, user_input, session_id=session_id, customer_id=customer_id)
        
        # For general questions or greetings, use OpenAI for natural responses
        customer_greeting = f"You are assisting {customer_name}, " if customer_name else "You are assisting a customer, "
        system_message = f"""You are a helpful and friendly airline customer service agent for SkyLine Airways.

{customer_greeting}an Indian customer.

Answer customer questions naturally and professionally about:
- Baggage policies (1 carry-on 10kg + 2 checked bags 23kg each for domestic, 2 checked bags 32kg each for international)
- Check-in times (24 hours before departure online, 3 hours before at airport for international)
- Airport arrival times (2 hours domestic, 3 hours international)
- Cancellation policies (free within 24 hours of booking, 50% refund up to 48 hours before)
- Visa requirements for international travel
- General travel advice and airline policies

Be warm, personalized, and helpful. Address the customer by name when appropriate. If they need to search flights, book tickets, check bookings, or manage reservations, guide them on how to ask."""

        # Build short recent history (last 10 messages) if available
        history_msgs = []
        if session_id and session_id in chat_histories:
            for m in chat_histories[session_id][-10:]:
                history_msgs.append({"role": m["role"], "content": m["content"]})

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_message},
                *history_msgs,
                {"role": "user", "content": user_input}
            ],
            temperature=0.7,
            max_tokens=300
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        print(f"OpenAI API error: {e}")
        # Fallback to basic routing
        decision = pick_tool_with_agent(user_input)
        tool = decision.get("tool", "rag")
        return execute_tool(tool, user_input, session_id=session_id, customer_id=customer_id)

def execute_tool(tool: str, user_input: str, session_id: Optional[str] = None, customer_id: Optional[int] = None) -> str:
    """Execute the selected tool"""
    if tool == "none":
        return (
            "✈️ **Namaste!** Welcome to SkyLine Airways.\n\n"
            "How can I assist you today?\n\n"
            "I can help you with:\n"
            "• Search and book flights\n"
            "• Check your bookings and travel history\n"
            "• View your profile and account details\n"
            "• Get flight information\n"
            "• Manage your reservations\n"
            "• Answer questions about our services"
        )
    elif tool == "search_flights":
        return search_flights_tool(user_input, session_id=session_id)
    elif tool == "book_flight":
        return book_flight_tool(user_input, session_id=session_id, customer_id=customer_id)
    elif tool == "check_booking":
        return check_booking_status_tool(user_input, customer_id=customer_id)
    elif tool == "manage_booking":
        return manage_booking_tool(user_input)
    elif tool == "customer_info":
        return customer_info_tool(user_input, customer_id=customer_id)
    elif tool == "flight_details":
        return flight_details_tool(user_input)
    elif tool == "complaint":
        return complaint_tool(user_input)
    else:
        return rag_tool(user_input)

# -------------------------------
# 7. FastAPI App + Startup/Shutdown
# -------------------------------
app = FastAPI(title="SDK Customer Service Agent")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    token: Optional[str] = None  # JWT token for authentication

class ChatResponse(BaseModel):
    user_input: str
    response: str
    session_id: Optional[str] = None

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    token: str
    customer_id: int
    name: str
    email: str
    message: str

@app.get("/health")
def health():
    return {"status": "ok", "embedder": bool(embedder), "vector_db": bool(vector_db)}

@app.post("/login", response_model=LoginResponse)
async def login_endpoint(req: LoginRequest):
    """Authenticate user and return JWT token"""
    try:
        user = authenticate_user(req.email, req.password)
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        token = create_token(user["customer_id"], user["email"])
        
        return {
            "token": token,
            "customer_id": user["customer_id"],
            "name": user["name"],
            "email": user["email"],
            "message": f"Welcome back, {user['name']}!"
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print("Error in /login:", tb)
        raise HTTPException(status_code=500, detail=f"⚠️ Server error: {str(e)}")

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    try:
        import uuid
        session_id = req.session_id or str(uuid.uuid4())

        # Extract customer info from token if provided
        customer_id = None
        customer_name = None
        if req.token:
            payload = verify_token(req.token)
            if payload:
                customer_id = payload.get("customer_id")
                # Get customer name
                try:
                    conn = _get_conn()
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM customers WHERE customer_id = ?", (customer_id,))
                    row = cur.fetchone()
                    if row:
                        customer_name = row[0]
                    conn.close()
                except Exception:
                    pass

        # Initialize chat history for this session
        if session_id not in chat_histories:
            chat_histories[session_id] = []

        # Record user message
        chat_histories[session_id].append({"role": "user", "content": req.message})

        # Get response using memory-aware tool picker with customer context
        response = tool_picker(req.message, session_id=session_id, customer_id=customer_id, customer_name=customer_name)

        # Record assistant reply
        chat_histories[session_id].append({"role": "assistant", "content": response})

        return {"user_input": req.message, "response": response, "session_id": session_id}
    except Exception as e:
        tb = traceback.format_exc()
        # log traceback to console so startup logs show it
        print("Error in /chat:", tb)
        raise HTTPException(status_code=500, detail=f"⚠️ Server error: {str(e)}")

@app.on_event("startup")
def startup_event():
    global embedder, vector_db, client
    print("Starting application: initialization beginning...")

    # Setup OpenAI client if not present but key exists
    if client is None and OpenAI is not None and OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            print("✅ OpenAI client initialized successfully.")
        except Exception as e:
            print(f"⚠️ OpenAI client initialization failed: {e}")
            print("Agent will use fallback routing without intelligent responses.")
            client = None
    elif not OPENAI_API_KEY:
        print("⚠️ OPENAI_API_KEY not set. Agent will use basic fallback routing.")
        print("To enable intelligent responses, set OPENAI_API_KEY environment variable.")

    # Initialize embedder (use fallback to avoid PyTorch loading issues)
    if embedder is None:
        # Skip SentenceTransformer due to DLL loading issues, use fallback directly
        if np is not None:
            embedder = FallbackEmbedder(dim=FAISS_DIM)
            print("FallbackEmbedder initialized (lightweight, no PyTorch required).")
        else:
            print("NumPy not available; fallback embedder cannot be created.")

    # Initialize vector DB
    if vector_db is None:
        if embedder is not None:
            try:
                vector_db = FaissVectorDB(embedder, dim=FAISS_DIM)
                print("FaissVectorDB initialized.")
            except Exception as e:
                print("Failed to initialize FaissVectorDB:", e)
                vector_db = None
        else:
            print("No embedder available; vector DB will not be initialized.")

    # Optionally load PDF documents into the RAG DB
    if PDF_PATH:
        if vector_db is not None:
            try:
                docs = load_pdf(PDF_PATH)
                if docs:
                    vector_db.add(docs)
                    print(f"Loaded {len(docs)} pages from PDF into vector DB.")
                else:
                    print("PDF loader ran but found no text.")
            except Exception as e:
                print("Error while loading PDF:", e)
        else:
            print("Vector DB not available; skipping PDF load.")

    print("Startup initialization complete.")

@app.on_event("shutdown")
def shutdown_event():
    print("Shutting down application...")

# If you want to run the app directly with `python backend_app.py` (not required when using uvicorn),
# uncomment below:
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend_app:app", host="127.0.0.1", port=8000, reload=True)
