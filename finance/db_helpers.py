# finance/db_helpers.py
import hashlib
from finance.db import engine
from finance.models import User
from sqlalchemy.orm import sessionmaker

Session = sessionmaker(bind=engine)

def hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def add_user(username: str, password: str) -> bool:
    """Add a new user if not already exists."""
    session = Session()
    existing_user = session.query(User).filter_by(username=username).first()
    if existing_user:
        print("⚠️ Username already exists!")
        return False

    hashed_pw = hash_password(password)
    new_user = User(username=username, password_hash=hashed_pw)
    session.add(new_user)
    session.commit()
    print(f"✅ User '{username}' added successfully!")
    return True

def list_users():
    """List all users."""
    session = Session()
    users = session.query(User).all()
    for user in users:
        print(user.id, user.username, user.password_hash)

def validate_login(username: str, password: str) -> bool:
    """Check if username exists and password is correct."""
    session = Session()
    user = session.query(User).filter_by(username=username).first()

    if not user:
        print("❌ Username not found!")
        return False

    hashed_pw = hash_password(password)
    if user.password_hash == hashed_pw:
        print("✅ Login successful!")
        return True
    else:
        print("❌ Incorrect password!")
        return False
