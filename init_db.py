import firebase_admin
from firebase_admin import credentials, firestore
import os

def init_db():
    """Initialize Firebase connection."""
    SERVICE_ACCOUNT_KEY = os.path.join(os.getcwd(), "serviceAccountKey.json")

    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY)
        firebase_admin.initialize_app(cred)

    print("✅ Firebase Initialized Successfully")
