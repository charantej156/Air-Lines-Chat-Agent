#!/usr/bin/env python3
"""
Test script for the airline chat application API
"""

import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_login():
    """Test the login endpoint"""
    print("=" * 50)
    print("Testing Login Endpoint")
    print("=" * 50)
    
    payload = {
        "email": "aadhvik@email.com",
        "password": "password123"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/login", json=payload)
        print(f"Status Code: {response.status_code}")
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        return data.get("token")
    except Exception as e:
        print(f"Error: {e}")
        return None

def test_chat_with_token(token):
    """Test the chat endpoint with authentication"""
    print("\n" + "=" * 50)
    print("Testing Chat Endpoint with Authentication")
    print("=" * 50)
    
    payload = {
        "message": "Show my bookings",
        "token": token
    }
    
    try:
        response = requests.post(f"{BASE_URL}/chat", json=payload)
        print(f"Status Code: {response.status_code}")
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

def test_chat_without_token():
    """Test the chat endpoint without authentication"""
    print("\n" + "=" * 50)
    print("Testing Chat Endpoint without Authentication")
    print("=" * 50)
    
    payload = {
        "message": "What flights do you have from New York to Los Angeles?"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/chat", json=payload)
        print(f"Status Code: {response.status_code}")
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

def test_health_check():
    """Test the health check endpoint"""
    print("\n" + "=" * 50)
    print("Testing Health Check Endpoint")
    print("=" * 50)
    
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Starting API Tests...\n")
    
    # Test health check
    test_health_check()
    
    # Test login
    token = test_login()
    
    # Test chat with authentication
    if token:
        test_chat_with_token(token)
    
    # Test chat without authentication
    test_chat_without_token()
    
    print("\n" + "=" * 50)
    print("API Tests Completed!")
    print("=" * 50)
