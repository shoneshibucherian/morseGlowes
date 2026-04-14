"""
setup_admin.py
══════════════
Run this ONCE in the VSCode terminal (with venv activated) to create
the OVERLORD admin account in MongoDB.

Usage:
    python setup_admin.py

After running, you can log in at http://localhost:5000/login with:
    Username : OVERLORD
    PIN      : (whatever you set below)
"""

from pymongo import MongoClient
from pymongo.server_api import ServerApi
import hashlib
import datetime

# ── Config ──
URI      = "mongodb://admin:password@localhost:27017/"
PIN      = "000000"   # ← CHANGE THIS to your desired admin PIN before running!

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

def main():
    client = MongoClient(URI, server_api=ServerApi('1'))
    try:
        client.admin.command('ping')
        print("✔ Connected to MongoDB.")
    except Exception as e:
        print(f"✘ Could not connect to MongoDB: {e}")
        return

    db        = client['Secret']
    users_col = db['users']

    # Check if OVERLORD already exists
    if users_col.find_one({'username_lower': 'admin'}):
        print("⚠ OVERLORD account already exists. Skipping.")
        return

    users_col.insert_one({
        '_id':           'admin',
        'username':      'admin',
        'username_lower':'admin',
        'pin_hash':      hash_pin(PIN),
        'color':         '#ff3b3b',   # Red — admin stands out
        'codename':      'OVERLORD',
        'role':          'admin',     # Special role flag
        'status':        'approved',
        'created_at':    datetime.datetime.now()
    })

    print("✔ OVERLORD admin account created successfully!")
    print(f"  Username : admin")
    print(f"  PIN      : {PIN}")
    print(f"  Role     : admin")
    print("\nYou can now log in at http://localhost:5000/login")
    print("Remember to change the PIN in this file before running in production!")

if __name__ == '__main__':
    main()
