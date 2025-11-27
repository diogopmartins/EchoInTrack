#!/usr/bin/env python3
"""
Script to set or update the admin password in the database.
Usage: python3 set_admin_password.py <password>
"""
import sys
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = 'echo.db'

if len(sys.argv) < 2:
    print("Usage: python3 set_admin_password.py <password>")
    print("Example: python3 set_admin_password.py mySecurePassword123")
    sys.exit(1)

new_password = sys.argv[1]

if len(new_password) < 6:
    print("Error: Password must be at least 6 characters long")
    sys.exit(1)

try:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Check if admin user exists
    c.execute('SELECT id FROM users WHERE username = ?', ('admin',))
    user = c.fetchone()
    
    hashed_password = generate_password_hash(new_password)
    
    if user:
        # Update existing admin user
        c.execute('UPDATE users SET password = ? WHERE username = ?', 
                  (hashed_password, 'admin'))
        print("✓ Admin password updated successfully")
    else:
        # Create new admin user
        c.execute('INSERT INTO users (username, password) VALUES (?, ?)', 
                  ('admin', hashed_password))
        print("✓ Admin user created successfully")
    
    conn.commit()
    conn.close()
    
    print(f"\nLogin credentials:")
    print(f"  Username: admin")
    print(f"  Password: {new_password}")
    print(f"\nYou can now log in at: http://localhost:8282")
    
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)

