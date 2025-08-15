# insert_user.py
from finance.db import engine
from finance.models import User
from sqlalchemy.orm import sessionmaker

# Create a session
Session = sessionmaker(bind=engine)
session = Session()

# Create a new user
new_user = User(username="testuser", password_hash="hashed_password_example")

# Add and commit to the database
session.add(new_user)
session.commit()

print("✅ User inserted successfully!")

# Fetch all users
users = session.query(User).all()
for user in users:
    print(user.id, user.username, user.password_hash)
