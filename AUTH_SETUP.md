# Multi-User Authentication Setup

## Overview
The airline chat agent now supports multiple users with secure authentication. Each user can only see their own bookings and profile information.

## Features Implemented

### 1. **User Authentication**
- JWT-based token authentication
- Bcrypt password hashing
- Secure login/logout flow
- Session persistence via localStorage

### 2. **Database Schema Updates**
- Added `password_hash` column to customers table
- Made email field unique for user identification
- Seeded 5 demo users with credentials

### 3. **API Endpoints**

#### `/login` (POST)
Authenticate user and receive JWT token.

**Request:**
```json
{
  "email": "aadhvik@email.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "customer_id": 1,
  "name": "Aadhvik Kosireddy",
  "email": "aadhvik@email.com",
  "message": "Welcome back, Aadhvik Kosireddy!"
}
```

#### `/chat` (POST)
Send chat messages with optional authentication token.

**Request:**
```json
{
  "message": "Show my bookings",
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "session_id": "optional-session-id"
}
```

### 4. **User-Scoped Data Access**
All tools now respect user boundaries:

- ✅ **Flight Search**: Public (all users see same flights)
- 🔒 **Bookings**: User can only see/manage their own bookings
- 🔒 **Profile**: User can only see their own profile
- 🔒 **Booking History**: Filtered by authenticated customer_id
- 🔒 **Previous Flight**: Shows only user's last flight

### 5. **Frontend Updates**
- Login screen with email/password form
- Token storage in localStorage
- User name display in header
- Logout functionality
- Demo credentials shown on login page

## Demo Users

All users have the same password: **password123**

| Name              | Email                     | Customer ID | Bookings |
|-------------------|---------------------------|-------------|----------|
| Aadhvik Kosireddy | aadhvik@email.com         | 1           | 3        |
| Priya Sharma      | priya.sharma@email.com    | 2           | 2        |
| Rahul Verma       | rahul.verma@email.com     | 3           | 2        |
| Ananya Reddy      | ananya.reddy@email.com    | 4           | 1        |
| Vikram Singh      | vikram.singh@email.com    | 5           | 1        |

## How to Use

### 1. Start the Backend
```bash
# Activate virtual environment
.venv\Scripts\activate

# Start FastAPI server
python backend/backend_app.py
```

### 2. Open Frontend
Open `TEMPLETE/chat.HTML` in your browser.

### 3. Login
Use any demo user credentials:
- Email: `aadhvik@email.com`
- Password: `password123`

### 4. Test Different Users
1. Login as Aadhvik and check bookings
2. Logout
3. Login as Priya and check bookings
4. Notice that each user only sees their own data

## Testing

Run the automated test script:
```bash
python test_auth.py
```

This will:
- Test login for multiple users
- Verify user-scoped data access
- Test booking without authentication (should fail)
- Test public flight search

## Security Features

### Password Security
- Passwords hashed using bcrypt
- Salt automatically generated
- Never stored in plain text

### Token Security
- JWT tokens expire after 24 hours
- Tokens signed with secret key
- Payload includes customer_id and email
- Token validated on every protected request

### Data Isolation
- All database queries filtered by customer_id
- No cross-user data leakage
- Tools require authentication for sensitive operations

## Environment Variables

Add to your environment or `.env` file:

```bash
OPENAI_API_KEY=your-openai-key
JWT_SECRET=your-secret-key-change-in-production  # Optional, has default
```

## API Response Examples

### Authenticated User Booking
```
✅ Booking Confirmed
Booking ID: 10 | PNR: PNR847362
Flight: AI101 | Seat: 12A
Payment: UPI | Fare: ₹5,500
Have a great trip!
```

### Unauthenticated Booking Attempt
```
❌ You must be logged in to book flights.
```

### User Profile (Own Data)
```
✈️ **Welcome, Aadhvik Kosireddy!**

📧 Email: aadhvik@email.com
📞 Phone: +91-98765-43210
🛂 Passport: M1234567
🎫 Frequent Flyer: FF789012
🌏 Nationality: Indian
✅ Account Status: Active

📋 **Your Booking History:**
...
```

## Migration Notes

### Breaking Changes
- `/chat` endpoint now accepts optional `token` field
- Tools now receive `customer_id` parameter
- `get_customer_data()` signature changed to accept `customer_id`

### Backward Compatibility
- Unauthenticated users can still search flights
- General questions work without login
- Chat works without token (but with limited features)

## Next Steps

Optional enhancements:
1. Password reset functionality
2. User registration endpoint
3. Email verification
4. Role-based access (admin, customer, agent)
5. Rate limiting per user
6. Audit logging of user actions
7. Two-factor authentication
8. Session management (active sessions, force logout)

## Troubleshooting

### "ModuleNotFoundError: No module named 'bcrypt'"
Install dependencies:
```bash
pip install bcrypt PyJWT
```

### "Invalid email or password"
Ensure you're using correct demo credentials or check database seeding.

### Token expired
Tokens expire after 24 hours. Login again to get a new token.

### Database schema error
Delete old database and recreate:
```bash
Remove-Item backend/airline_customers.db
python backend/create_airline_db.py
```
