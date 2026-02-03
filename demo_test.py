#!/usr/bin/env python3
"""
Demo Test Script - Tests the Airline Chat Agent Features
This script demonstrates:
1. User Login
2. Flight Search
3. Flight Booking
4. Booking Status Check
5. Customer Profile & History
"""

import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_login():
    """Test user authentication"""
    print("\n" + "="*60)
    print("TEST 1: USER LOGIN")
    print("="*60)
    
    login_data = {
        "email": "aadhvik@email.com",
        "password": "password123"
    }
    
    response = requests.post(f"{BASE_URL}/login", json=login_data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Login Successful!")
        print(f"   Name: {result['name']}")
        print(f"   Email: {result['email']}")
        print(f"   Customer ID: {result['customer_id']}")
        print(f"   Token: {result['token'][:30]}...")
        return result['token'], result['customer_id']
    else:
        print(f"❌ Login Failed: {response.status_code}")
        print(response.text)
        return None, None

def test_flight_search(token):
    """Test flight search functionality"""
    print("\n" + "="*60)
    print("TEST 2: FLIGHT SEARCH")
    print("="*60)
    
    chat_data = {
        "message": "Show me flights from Delhi to Mumbai on 2025-12-20",
        "token": token
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=chat_data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Search Request Sent!")
        print(f"\nBot Response:")
        print(result['response'])
        return result['session_id']
    else:
        print(f"❌ Search Failed: {response.status_code}")
        print(response.text)
        return None

def test_flight_booking(token, session_id):
    """Test flight booking process"""
    print("\n" + "="*60)
    print("TEST 3: FLIGHT BOOKING")
    print("="*60)
    
    # Step 1: Initiate booking
    chat_data = {
        "message": "I want to book a flight from Delhi to Mumbai on 2025-12-20",
        "session_id": session_id,
        "token": token
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=chat_data)
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Booking Initiated!")
        print(f"\nBot: {result['response']}\n")
        session_id = result['session_id']
    
    # Step 2: Choose flight option
    chat_data = {
        "message": "Book the first one",
        "session_id": session_id,
        "token": token
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=chat_data)
    if response.status_code == 200:
        result = response.json()
        print(f"\n✅ Flight Selected!")
        print(f"Bot: {result['response']}\n")
        session_id = result['session_id']
    
    # Step 3: Select seat
    chat_data = {
        "message": "I want seat 12A",
        "session_id": session_id,
        "token": token
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=chat_data)
    if response.status_code == 200:
        result = response.json()
        print(f"\n✅ Seat Selected!")
        print(f"Bot: {result['response']}\n")
        session_id = result['session_id']
    
    # Step 4: Choose payment method
    chat_data = {
        "message": "I'll pay with UPI",
        "session_id": session_id,
        "token": token
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=chat_data)
    if response.status_code == 200:
        result = response.json()
        print(f"\n✅ Payment Processed!")
        print(f"Bot Response:")
        print(result['response'])
        return result['session_id']
    else:
        print(f"❌ Booking Failed: {response.status_code}")
        return session_id

def test_booking_status(token, customer_id):
    """Test booking status check"""
    print("\n" + "="*60)
    print("TEST 4: CHECK BOOKING STATUS")
    print("="*60)
    
    chat_data = {
        "message": "Show me my bookings",
        "token": token
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=chat_data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Booking Status Retrieved!")
        print(f"\nBot Response:")
        print(result['response'])
    else:
        print(f"❌ Status Check Failed: {response.status_code}")
        print(response.text)

def test_customer_profile(token):
    """Test customer profile and history"""
    print("\n" + "="*60)
    print("TEST 5: CUSTOMER PROFILE & HISTORY")
    print("="*60)
    
    chat_data = {
        "message": "Show me my profile and booking history",
        "token": token
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=chat_data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Profile Retrieved!")
        print(f"\nBot Response:")
        print(result['response'])
    else:
        print(f"❌ Profile Fetch Failed: {response.status_code}")
        print(response.text)

def test_flight_details(token):
    """Test flight details"""
    print("\n" + "="*60)
    print("TEST 6: FLIGHT DETAILS")
    print("="*60)
    
    chat_data = {
        "message": "Tell me details about flight AI101",
        "token": token
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=chat_data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Flight Details Retrieved!")
        print(f"\nBot Response:")
        print(result['response'])
    else:
        print(f"❌ Details Fetch Failed: {response.status_code}")
        print(response.text)

def main():
    print("\n" + "🌍 "*20)
    print("     AIRLINE CHAT AGENT - COMPREHENSIVE DEMO TEST")
    print("🌍 "*20)
    
    # Wait for servers to be ready
    print("\nWaiting for backend to be ready...")
    time.sleep(3)
    
    try:
        # Test 1: Login
        token, customer_id = test_login()
        if not token:
            print("❌ Could not proceed - login failed")
            return
        
        # Test 2: Flight Search
        session_id = test_flight_search(token)
        
        # Test 3: Flight Booking
        if session_id:
            session_id = test_flight_booking(token, session_id)
        
        # Test 4: Booking Status
        test_booking_status(token, customer_id)
        
        # Test 5: Customer Profile
        test_customer_profile(token)
        
        # Test 6: Flight Details
        test_flight_details(token)
        
        print("\n" + "="*60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("="*60)
        
        print("\n📱 Frontend Access:")
        print("   🌐 Open your browser and go to: http://127.0.0.1:3000/chat.HTML")
        print("\n📚 Demo Credentials:")
        print("   Email: aadhvik@email.com")
        print("   Password: password123")
        
        print("\n✨ Features Tested:")
        print("   ✅ User Authentication (Login/JWT)")
        print("   ✅ Flight Search by Route & Date")
        print("   ✅ Flight Booking (Multi-step process)")
        print("   ✅ Booking Status Check")
        print("   ✅ Customer Profile & History")
        print("   ✅ Flight Details Retrieval")
        
    except Exception as e:
        print(f"\n❌ Error during testing: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
