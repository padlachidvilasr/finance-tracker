# login_user.py
from finance.db_helpers import validate_login

# Test login
validate_login("alice", "mysecretpassword")  # ✅ Should pass
validate_login("alice", "wrongpassword")     # ❌ Should fail
validate_login("bob", "any")                 # ❌ Username not found
