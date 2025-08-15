# add_user.py
from finance.db_helpers import add_user, list_users

# Add a test user
add_user("alice", "mysecretpassword")

# List all users
list_users()
