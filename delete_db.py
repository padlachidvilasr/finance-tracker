# delete_db.py
import os
import sqlite3

db_path = "data/finance.db"

# Close any lingering connection by opening and closing once
try:
    conn = sqlite3.connect(db_path)
    conn.close()
except:
    pass

# Now delete
if os.path.exists(db_path):
    os.remove(db_path)
    print("Database deleted.")
else:
    print("Database not found.")
