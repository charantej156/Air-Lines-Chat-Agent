"""Test script for authentication"""
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

# Test 1: Login as Aadhvik
print("=" * 50)
print("Test 1: Login as Aadhvik")
print("=" * 50)
login_data = {
    "email": "aadhvik@email.com",
    "password": "password123"
}
response = requests.post(f"{BASE_URL}/login", json=login_data)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"Token: {data['token'][:50]}...")
    print(f"Name: {data['name']}")
    print(f"Customer ID: {data['customer_id']}")
    aadhvik_token = data['token']
else:
    print(f"Error: {response.text}")
    exit(1)

# Test 2: Get customer info with token
print("\n" + "=" * 50)
print("Test 2: Get Aadhvik's profile")
print("=" * 50)
chat_data = {
    "message": "Show my account details",
    "token": aadhvik_token
}
response = requests.post(f"{BASE_URL}/chat", json=chat_data)
if response.status_code == 200:
    data = response.json()
    print(f"Response:\n{data['response'][:300]}...")
else:
    print(f"Error: {response.text}")

# Test 3: Login as Priya
print("\n" + "=" * 50)
print("Test 3: Login as Priya")
print("=" * 50)
login_data = {
    "email": "priya.sharma@email.com",
    "password": "password123"
}
response = requests.post(f"{BASE_URL}/login", json=login_data)
if response.status_code == 200:
    data = response.json()
    print(f"Name: {data['name']}")
    priya_token = data['token']
else:
    print(f"Error: {response.text}")
    exit(1)

# Test 4: Get Priya's bookings (should be different from Aadhvik's)
print("\n" + "=" * 50)
print("Test 4: Get Priya's bookings")
print("=" * 50)
chat_data = {
    "message": "Show my booking history",
    "token": priya_token
}
response = requests.post(f"{BASE_URL}/chat", json=chat_data)
if response.status_code == 200:
    data = response.json()
    print(f"Response:\n{data['response'][:300]}...")
else:
    print(f"Error: {response.text}")

# Test 5: Try to book without token (should fail)
print("\n" + "=" * 50)
print("Test 5: Try to book without authentication")
print("=" * 50)
chat_data = {
    "message": "Book AI101"
}
response = requests.post(f"{BASE_URL}/chat", json=chat_data)
if response.status_code == 200:
    data = response.json()
    print(f"Response: {data['response']}")
else:
    print(f"Error: {response.text}")

# Test 6: Search flights (no auth needed)
print("\n" + "=" * 50)
print("Test 6: Search flights (public)")
print("=" * 50)
chat_data = {
    "message": "Flights from Delhi to Mumbai"
}
response = requests.post(f"{BASE_URL}/chat", json=chat_data)
if response.status_code == 200:
    data = response.json()
    print(f"Response:\n{data['response'][:300]}...")
else:
    print(f"Error: {response.text}")

print("\n" + "=" * 50)
print("All tests completed!")
print("=" * 50)
