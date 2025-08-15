# test_db.py
from finance.db import engine

try:
    conn = engine.connect()
    print("✅ Database connection successful!")
    conn.close()
except Exception as e:
    print("❌ Database connection failed:", e)
