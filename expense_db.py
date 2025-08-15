import firebase_admin
from firebase_admin import credentials, firestore
import os

# Path to your Firebase service account key JSON file
SERVICE_ACCOUNT_KEY = os.path.join(os.getcwd(), "serviceAccountKey.json")

# Initialize Firebase only once
if not firebase_admin._apps:
    cred = credentials.Certificate(SERVICE_ACCOUNT_KEY)
    firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()

# ===== User Functions =====
def create_user(username, password):
    users_ref = db.collection("users")
    existing_user = users_ref.where("username", "==", username).get()
    if existing_user:
        return False  # Username already exists
    users_ref.add({"username": username, "password": password})
    return True

def get_user(username, password):
    users_ref = db.collection("users")
    user_query = users_ref.where("username", "==", username).where("password", "==", password).get()
    if user_query:
        return user_query[0].id  # Return user document ID
    return None

# ===== Expense Functions =====
def add_expense(user_id, date, category, amount, description):
    db.collection("expenses").add({
        "user_id": user_id,
        "date": date,
        "category": category,
        "amount": amount,
        "description": description
    })

def get_expenses(user_id):
    expenses = db.collection("expenses").where("user_id", "==", user_id).stream()
    return [{"id": e.id, **e.to_dict()} for e in expenses]

def delete_expense(expense_id):
    db.collection("expenses").document(expense_id).delete()

# ===== Budget Functions =====
def set_monthly_budget(user_id, month, budget):
    budgets_ref = db.collection("monthly_budgets")
    existing_budget = budgets_ref.where("user_id", "==", user_id).where("month", "==", month).get()
    if existing_budget:
        # Update existing budget
        budgets_ref.document(existing_budget[0].id).update({"budget": budget})
    else:
        budgets_ref.add({"user_id": user_id, "month": month, "budget": budget})

def get_monthly_budget(user_id, month):
    budgets_ref = db.collection("monthly_budgets")
    budget = budgets_ref.where("user_id", "==", user_id).where("month", "==", month).get()
    if budget:
        return budget[0].to_dict()["budget"]
    return None
