# app.py - Smart Personal Finance Tracker (Firebase, robust queries + index handling)
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import hashlib
import os
from datetime import date, datetime
from io import BytesIO
import tempfile
import re
import time

# Optional PDF generation
try:
    from fpdf import FPDF
    _FPDF_AVAILABLE = True
except Exception:
    _FPDF_AVAILABLE = False

# Firebase admin SDK
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    from google.cloud.firestore_v1.base_query import FieldFilter
    from google.api_core.exceptions import FailedPrecondition, ServiceUnavailable, RetryError
    _FIREBASE_AVAILABLE = True
except Exception as e:
    firebase_admin = None
    firestore = None
    FieldFilter = None
    FailedPrecondition = Exception
    ServiceUnavailable = Exception
    RetryError = Exception
    _FIREBASE_AVAILABLE = False
    init_error_msg = str(e)

# ---------- CONFIG ----------
st.set_page_config(page_title="Smart Personal Finance Tracker", layout="wide")
BASE_DIR = os.path.dirname(__file__)
REPORTS_DIR = os.path.join(BASE_DIR, "data", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# ---------- FIREBASE INITIALIZATION ----------
def init_firebase():
    """Initialize firebase-admin and return a firestore client.
       Expects firebase_key.json in project root.
    """
    if not _FIREBASE_AVAILABLE:
        raise RuntimeError("firebase-admin (and related libs) are not installed: pip install firebase-admin google-api-core")
    if not firebase_admin._apps:
        key_path = os.path.join(BASE_DIR, "firebase_key.json")
        if not os.path.exists(key_path):
            raise FileNotFoundError("firebase_key.json not found in project root. Place your Firebase service account JSON there.")
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# Try initializing once; if fails, we'll show a clear error in the UI.
try:
    db = init_firebase()
    FIRESTORE_OK = True
except Exception as e:
    db = None
    FIRESTORE_OK = False
    init_error_msg = str(e)

# ---------- Utilities ----------
def sha256_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def doc_to_dict(doc):
    d = doc.to_dict()
    d["_id"] = doc.id
    return d

def extract_index_url_from_error(exc_text: str) -> str:
    """Look for a firebase console URL inside an exception message and return it (if any)."""
    # Firebase index creation URLs typically contain 'console.firebase.google.com' and 'create_composite='
    m = re.search(r"(https?://console\.firebase\.google\.com/[^ ]*create_composite=[^ \n\r]+)", exc_text)
    if m:
        return m.group(1)
    # sometimes it's slightly different - fallback search
    m2 = re.search(r"(https?://console\.firebase\.google\.com/[^\s]+/indexes\?[^\s]+)", exc_text)
    if m2:
        return m2.group(1)
    return ""

def safe_get(query, timeout=30):
    """Call query.get(timeout=...) with friendly error handling and return docs or None."""
    try:
        return query.get(timeout=timeout)
    except FailedPrecondition as fp:
        # Firestore index required
        url = extract_index_url_from_error(str(fp))
        raise FailedPrecondition(f"Index required: {fp}. Create it here: {url}") from fp
    except ServiceUnavailable as su:
        raise ServiceUnavailable(f"Service temporarily unavailable: {su}") from su
    except RetryError as rexc:
        raise rexc
    except Exception as e:
        raise e

def collection_to_df(collection_ref, filters=None, order_by=None, limit=None, timeout=30):
    """
    Build a Firestore query from filters (list of (field, op, value)) using FieldFilter,
    run it with timeout and return a pandas DataFrame.
    """
    if not FIRESTORE_OK:
        raise RuntimeError("Firestore not initialized")
    q = collection_ref
    if filters:
        for f in filters:
            # use FieldFilter to avoid positional-arg warnings
            try:
                ff = FieldFilter(f[0], f[1], f[2])
                q = q.where(filter=ff)
            except Exception:
                # fallback to positional if FieldFilter unavailable
                q = q.where(f[0], f[1], f[2])
    if order_by:
        # Firestore requires order_by field to be indexed with filters; calling may raise FailedPrecondition
        q = q.order_by(order_by)
    if limit:
        q = q.limit(limit)
    # execute with safe_get (handles index errors etc)
    docs = safe_get(q, timeout=timeout)
    rows = [doc_to_dict(d) for d in docs]
    if rows:
        df = pd.DataFrame(rows)
        # ensure expected columns exist and types
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        if "date" in df.columns:
            # keep as string for simplicity; parse where needed
            df["date"] = df["date"].astype(str)
        return df
    else:
        return pd.DataFrame()

# ---------- Firestore-backed CRUD ----------
def ensure_firestore_ready_ui():
    if not FIRESTORE_OK:
        st.error("Firebase initialization failed: " + (init_error_msg if 'init_error_msg' in globals() else "unknown"))
        st.info("Add firebase_key.json (service account) to project root and ensure firebase-admin is installed.")
        st.stop()

# Users
def create_user(username: str, password: str):
    ensure_firestore_ready_ui()
    users_ref = db.collection("users")
    try:
        # check existence
        docs = safe_get(users_ref.where(filter=FieldFilter("username", "==", username)).limit(1))
        if docs and len(list(docs)) > 0:
            return False, "Username already exists"
        hashed = sha256_hash(password)
        new_user = users_ref.add({"username": username, "password": hashed, "created_at": firestore.SERVER_TIMESTAMP})
        # get created id (second element)
        user_id = new_user[1].id if isinstance(new_user, tuple) else new_user.id
        # create default categories using batch
        defaults_exp = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Other"]
        defaults_inc = ["Salary", "Interest", "Gift", "Other"]
        batch = db.batch()
        cat_ref = db.collection("categories")
        for c in defaults_exp:
            d = cat_ref.document()
            batch.set(d, {"user_id": user_id, "name": c, "type": "expense"})
        for c in defaults_inc:
            d = cat_ref.document()
            batch.set(d, {"user_id": user_id, "name": c, "type": "income"})
        batch.commit()
        return True, "Created"
    except FailedPrecondition as fp:
        url = extract_index_url_from_error(str(fp))
        return False, f"Firestore index required: create it here: {url}" 
    except Exception as e:
        return False, f"Error: {e}"

def authenticate(username: str, password: str):
    ensure_firestore_ready_ui()
    users_ref = db.collection("users")
    hashed = sha256_hash(password)
    try:
        # use FieldFilter to avoid positional-arg warnings
        q = users_ref.where(filter=FieldFilter("username", "==", username)).where(filter=FieldFilter("password", "==", hashed)).limit(1)
        docs = safe_get(q, timeout=20)
        docs_list = list(docs)
        if docs_list:
            return docs_list[0].id
        return None
    except FailedPrecondition as fp:
        url = extract_index_url_from_error(str(fp))
        st.error("Firestore index required for this query. Create it here:\n" + (url or str(fp)))
        return None
    except ServiceUnavailable as su:
        st.error("Firestore service temporarily unavailable. Try again in a moment.")
        return None
    except Exception as e:
        st.error(f"Auth error: {e}")
        return None

# Categories
def get_categories(user_id: str, ctype="expense"):
    ensure_firestore_ready_ui()
    col = db.collection("categories")
    try:
        df = collection_to_df(col, filters=[("user_id","==",user_id),("type","==",ctype)], order_by="name", timeout=20)
        return df["name"].tolist() if not df.empty else []
    except FailedPrecondition as fp:
        # index required
        url = extract_index_url_from_error(str(fp))
        st.error(f"Index required for categories query. Create index: {url}")
        return []
    except Exception as e:
        st.error(f"Could not fetch categories: {e}")
        return []

def add_category(user_id: str, name: str, ctype: str):
    ensure_firestore_ready_ui()
    col = db.collection("categories")
    try:
        existing = safe_get(col.where(filter=FieldFilter("user_id","==",user_id)).where(filter=FieldFilter("name","==",name)).where(filter=FieldFilter("type","==",ctype)).limit(1), timeout=15)
        if list(existing):
            return False
    except Exception:
        # ignore index issues - try a last resort
        pass
    col.add({"user_id": user_id, "name": name, "type": ctype})
    return True

# Expenses & incomes
def add_expense(user_id: str, date_s: str, category: str, amount: float, description: str = ""):
    ensure_firestore_ready_ui()
    try:
        db.collection("expenses").add({
            "user_id": user_id,
            "date": date_s,
            "category": category,
            "amount": float(amount),
            "description": description,
            "created_at": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        st.error(f"Could not add expense: {e}")
        return False

def get_expenses(user_id: str, start_date=None, end_date=None, category=None, qtext=None, min_amt=None, max_amt=None, limit=1000):
    ensure_firestore_ready_ui()
    col = db.collection("expenses")
    filters = [("user_id","==",user_id)]
    if start_date:
        filters.append(("date", ">=", start_date))
    if end_date:
        filters.append(("date", "<=", end_date))
    if category:
        filters.append(("category", "==", category))
    try:
        df = collection_to_df(col, filters=filters, order_by="date", limit=limit, timeout=30)
    except FailedPrecondition as fp:
        url = extract_index_url_from_error(str(fp))
        st.error("Firestore index required for expenses query. Create it here:\n" + (url or str(fp)))
        return pd.DataFrame()
    except ServiceUnavailable as su:
        st.error("Firestore temporarily unavailable. Try again later.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Could not read expenses: {e}")
        return pd.DataFrame()
    # local filters for description and amounts
    if df.empty:
        return df
    if qtext:
        df = df[df["description"].str.lower().str.contains(qtext.lower(), na=False)]
    if min_amt is not None:
        df = df[df["amount"] >= float(min_amt)]
    if max_amt is not None:
        df = df[df["amount"] <= float(max_amt)]
    # sort descending by date (string compare works for YYYY-MM-DD)
    df = df.sort_values("date", ascending=False)
    return df

def add_income(user_id: str, date_s: str, category: str, amount: float, description: str = ""):
    ensure_firestore_ready_ui()
    try:
        db.collection("incomes").add({
            "user_id": user_id,
            "date": date_s,
            "category": category,
            "amount": float(amount),
            "description": description,
            "created_at": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        st.error(f"Could not add income: {e}")
        return False

def get_incomes(user_id: str, start_date=None, end_date=None, category=None, qtext=None, min_amt=None, max_amt=None, limit=1000):
    ensure_firestore_ready_ui()
    col = db.collection("incomes")
    filters = [("user_id","==",user_id)]
    if start_date:
        filters.append(("date", ">=", start_date))
    if end_date:
        filters.append(("date", "<=", end_date))
    if category:
        filters.append(("category", "==", category))
    try:
        df = collection_to_df(col, filters=filters, order_by="date", limit=limit, timeout=30)
    except FailedPrecondition as fp:
        url = extract_index_url_from_error(str(fp))
        st.error("Firestore index required for incomes query. Create it here:\n" + (url or str(fp)))
        return pd.DataFrame()
    except ServiceUnavailable:
        st.error("Firestore temporarily unavailable. Try again later.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Could not read incomes: {e}")
        return pd.DataFrame()
    if df.empty:
        return df
    if qtext:
        df = df[df["description"].str.lower().str.contains(qtext.lower(), na=False)]
    if min_amt is not None:
        df = df[df["amount"] >= float(min_amt)]
    if max_amt is not None:
        df = df[df["amount"] <= float(max_amt)]
    df = df.sort_values("date", ascending=False)
    return df

# Budgets
def set_monthly_budget(user_id: str, month: str, budget: float):
    ensure_firestore_ready_ui()
    col = db.collection("budgets")
    try:
        docs = safe_get(col.where(filter=FieldFilter("user_id","==",user_id)).where(filter=FieldFilter("month","==",month)).limit(1), timeout=15)
        docs_list = list(docs)
        if docs_list:
            col.document(docs_list[0].id).update({"budget": float(budget)})
        else:
            col.add({"user_id": user_id, "month": month, "budget": float(budget)})
    except Exception as e:
        st.error(f"Could not set budget: {e}")

def get_monthly_budget(user_id: str, month: str):
    ensure_firestore_ready_ui()
    col = db.collection("budgets")
    try:
        docs = safe_get(col.where(filter=FieldFilter("user_id","==",user_id)).where(filter=FieldFilter("month","==",month)).limit(1), timeout=15)
        docs_list = list(docs)
        if docs_list:
            return docs_list[0].to_dict().get("budget")
        return None
    except Exception as e:
        st.error(f"Could not fetch budget: {e}")
        return None

def set_category_budget(user_id: str, month: str, category: str, budget: float):
    ensure_firestore_ready_ui()
    col = db.collection("category_budgets")
    try:
        docs = safe_get(col.where(filter=FieldFilter("user_id","==",user_id)).where(filter=FieldFilter("month","==",month)).where(filter=FieldFilter("category","==",category)).limit(1), timeout=15)
        dl = list(docs)
        if dl:
            col.document(dl[0].id).update({"budget": float(budget)})
        else:
            col.add({"user_id": user_id, "month": month, "category": category, "budget": float(budget)})
    except Exception as e:
        st.error(f"Could not set category budget: {e}")

def get_category_budget(user_id: str, month: str, category: str):
    ensure_firestore_ready_ui()
    col = db.collection("category_budgets")
    try:
        docs = safe_get(col.where(filter=FieldFilter("user_id","==",user_id)).where(filter=FieldFilter("month","==",month)).where(filter=FieldFilter("category","==",category)).limit(1), timeout=15)
        dl = list(docs)
        if dl:
            return dl[0].to_dict().get("budget")
        return None
    except Exception as e:
        st.error(f"Could not fetch category budget: {e}")
        return None

# ---------- PDF generation ----------
def generate_pdf(user_id: str, month: str):
    if not _FPDF_AVAILABLE:
        raise RuntimeError("Install fpdf2: pip install fpdf2")
    start = month + "-01"; end = month + "-31"
    exp_df = get_expenses(user_id, start_date=start, end_date=end)
    inc_df = get_incomes(user_id, start_date=start, end_date=end)
    tot_exp = exp_df["amount"].sum() if not exp_df.empty else 0.0
    tot_inc = inc_df["amount"].sum() if not inc_df.empty else 0.0
    net = tot_inc - tot_exp
    budget = get_monthly_budget(user_id, month)
    imgs = []
    if not exp_df.empty:
        fig, ax = plt.subplots(figsize=(6,3))
        s = exp_df.groupby("category")["amount"].sum().sort_values(ascending=False)
        s.plot(kind="bar", ax=ax)
        ax.set_ylabel("Amount")
        ax.set_xticks(range(len(s.index)))
        ax.set_xticklabels(s.index, rotation=30, ha="right")
        plt.tight_layout()
        buf = BytesIO(); fig.savefig(buf, format="png"); buf.seek(0); imgs.append(buf); plt.close(fig)
    if not inc_df.empty:
        fig, ax = plt.subplots(figsize=(6,3))
        s = inc_df.groupby("category")["amount"].sum().sort_values(ascending=False)
        s.plot(kind="bar", ax=ax)
        ax.set_ylabel("Amount")
        ax.set_xticks(range(len(s.index)))
        ax.set_xticklabels(s.index, rotation=30, ha="right")
        plt.tight_layout()
        buf = BytesIO(); fig.savefig(buf, format="png"); buf.seek(0); imgs.append(buf); plt.close(fig)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"Finance Report - {month}", ln=True, align="C")
    pdf.ln(4)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 8, f"Total Income: {tot_inc:.2f}", ln=True)
    pdf.cell(0, 8, f"Total Expenses: {tot_exp:.2f}", ln=True)
    pdf.cell(0, 8, f"Net Savings: {net:.2f}", ln=True)
    if budget is not None:
        pdf.cell(0, 8, f"Budget: {budget:.2f}", ln=True)
    pdf.ln(6)
    for imgbuf in imgs:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(imgbuf.getbuffer()); tmp.flush(); tmp.close()
        pdf.image(tmp.name, w=180)
        os.unlink(tmp.name)
        pdf.ln(4)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Top expenses (sample)", ln=True)
    pdf.set_font("Arial", size=10)
    if not exp_df.empty:
        sample = exp_df.head(20)
        pdf.set_fill_color(230,230,230)
        pdf.cell(40,7,"Date",1,0,'C',fill=True)
        pdf.cell(70,7,"Category",1,0,'C',fill=True)
        pdf.cell(40,7,"Amount",1,1,'C',fill=True)
        for _, r in sample.iterrows():
            pdf.cell(40,7,str(r['date']),1,0)
            pdf.cell(70,7,str(r['category'])[:30],1,0)
            pdf.cell(40,7,f"{r['amount']:.2f}",1,1)
    else:
        pdf.cell(0,8,"No expenses in this month.", ln=True)
    out = os.path.join(REPORTS_DIR, f"report_user_{user_id}_{month}.pdf")
    pdf.output(out)
    return out

# ---------- UI ----------
# Dark mode toggle (basic)
if "dark" not in st.session_state:
    st.session_state.dark = False
if st.sidebar.checkbox("Dark mode", value=st.session_state.dark):
    st.session_state.dark = True
    st.markdown("""<style>body{background:#0f1720;color:#e2e8f0} .stButton>button{background:#1f2937}</style>""", unsafe_allow_html=True)
else:
    st.session_state.dark = False

# Session variables
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None

st.title("💼 Smart Personal Finance Tracker (Firebase)")

# If Firebase failed to initialize, show instructions
if not FIRESTORE_OK:
    st.error("Firebase initialization failed: " + str(init_error_msg))
    st.info("Place firebase_key.json (service account) in the project root and install firebase-admin.")
    st.stop()

# Authentication UI
if st.session_state.user_id is None:
    colL, colR = st.columns(2)
    with colL:
        st.subheader("🔑 Login")
        u_login = st.text_input("Username", key="u_login")
        p_login = st.text_input("Password", type="password", key="p_login")
        if st.button("Login"):
            uid = authenticate(u_login.strip(), p_login.strip())
            if uid:
                st.session_state.user_id = uid
                st.session_state.username = u_login.strip()
                st.success("Logged in")
                st.experimental_rerun() if hasattr(st, "experimental_rerun") else st.rerun()
            else:
                st.error("Invalid username/password or an error occurred (check messages above).")
    with colR:
        st.subheader("🆕 Create account")
        u_new = st.text_input("Choose username", key="u_new")
        p_new = st.text_input("Choose password", type="password", key="p_new")
        if st.button("Sign up"):
            if u_new.strip() and p_new.strip():
                ok, msg = create_user(u_new.strip(), p_new.strip())
                if ok:
                    st.success("Account created — now login.")
                else:
                    st.error(msg)
            else:
                st.warning("Fill both fields.")
    st.stop()

# logged in
uid = st.session_state.user_id
st.sidebar.write(f"Signed in as **{st.session_state.username}**")
if st.sidebar.button("Logout"):
    st.session_state.clear(); st.experimental_rerun() if hasattr(st, "experimental_rerun") else st.rerun()

tabs = st.tabs(["Dashboard","Expenses","Income","Categories","Budgets","Reports","Settings"])

# ---------- Dashboard ----------
with tabs[0]:
    st.subheader("Overview")
    today = date.today()
    current_month = today.strftime("%Y-%m")
    exp_df = get_expenses(uid)
    inc_df = get_incomes(uid)
    month_exp = exp_df[exp_df['date'].str.startswith(current_month)]['amount'].sum() if not exp_df.empty else 0.0
    month_inc = inc_df[inc_df['date'].str.startswith(current_month)]['amount'].sum() if not inc_df.empty else 0.0
    budget = get_monthly_budget(uid, current_month)
    col1, col2, col3 = st.columns(3)
    col1.metric("Income (this month)", f"{month_inc:.2f}")
    col2.metric("Expense (this month)", f"{month_exp:.2f}")
    col3.metric("Net savings", f"{(month_inc - month_exp):.2f}")
    if budget:
        st.info(f"Monthly budget for {current_month}: {budget:.2f}")
        if month_exp > budget:
            st.error("⚠ You exceeded your monthly budget!")
        elif month_exp > 0.8 * budget:
            st.warning("⚠ You're nearing the budget")
    if not exp_df.empty:
        st.markdown("### Expenses By Category (all time)")
        cat_sum = exp_df.groupby("category")["amount"].sum().sort_values(ascending=False)
        fig, ax = plt.subplots()
        ax.bar(cat_sum.index, cat_sum.values)
        ax.set_xticks(range(len(cat_sum.index)))
        ax.set_xticklabels(cat_sum.index, rotation=30, ha='right')
        ax.set_ylabel("Amount")
        plt.tight_layout()
        st.pyplot(fig)

# ---------- Expenses tab ----------
with tabs[1]:
    st.subheader("Add Expense")
    with st.form("frm_add_exp"):
        d = st.date_input("Date", value=date.today())
        cats = get_categories(uid, "expense")
        cat = st.selectbox("Category", cats if cats else ["Other"])
        newc = st.text_input("Or add new expense category", "")
        amt = st.number_input("Amount", min_value=0.0, format="%.2f")
        desc = st.text_area("Description")
        if st.form_submit_button("Save expense"):
            if newc.strip():
                add_category(uid, newc.strip(), "expense"); cat = newc.strip()
            ok = add_expense(uid, d.strftime("%Y-%m-%d"), cat, float(amt), desc)
            if ok:
                st.success("Saved.")
            else:
                st.error("Failed to save expense.")

    st.subheader("Your Expenses")
    colA, colB, colC = st.columns([1,1,1])
    with colA:
        start = st.date_input("Start", value=date(today.year, today.month, 1), key="exp_start")
    with colB:
        end = st.date_input("End", value=date.today(), key="exp_end")
    with colC:
        cat_f = st.selectbox("Category", ["All"] + get_categories(uid, "expense"))
    qtext = st.text_input("Search description (optional)")
    min_amt = st.number_input("Min amount (optional)", value=0.0)
    max_amt = st.number_input("Max amount (optional)", value=0.0)
    df_exp = get_expenses(uid, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), None if cat_f=="All" else cat_f,
                          qtext if qtext.strip() else None,
                          min_amt if min_amt>0 else None,
                          max_amt if max_amt>0 else None)
    if not df_exp.empty:
        st.dataframe(df_exp, use_container_width=True)
        st.download_button("Download expenses CSV", df_exp.to_csv(index=False).encode("utf-8"), "expenses.csv", "text/csv")
    else:
        st.info("No expenses for selected filters.")

# ---------- Income tab ----------
with tabs[2]:
    st.subheader("Add Income")
    with st.form("frm_add_inc"):
        d = st.date_input("Date", value=date.today(), key="inc_date")
        cats = get_categories(uid, "income")
        cat = st.selectbox("Category", cats if cats else ["Salary"], key="inc_cat")
        newc = st.text_input("Or add new income category", "", key="new_inc_cat")
        amt = st.number_input("Amount", min_value=0.0, format="%.2f", key="inc_amt")
        desc = st.text_area("Description", key="inc_desc")
        if st.form_submit_button("Save income"):
            if newc.strip():
                add_category(uid, newc.strip(), "income"); cat = newc.strip()
            ok = add_income(uid, d.strftime("%Y-%m-%d"), cat, float(amt), desc)
            if ok:
                st.success("Saved.")
            else:
                st.error("Failed to save income.")

    st.subheader("Your Incomes")
    colA, colB, colC = st.columns([1,1,1])
    with colA: start = st.date_input("Start income", value=date(today.year, today.month, 1), key="inc_start")
    with colB: end = st.date_input("End income", value=date.today(), key="inc_end")
    with colC:
        cat_f = st.selectbox("Category", ["All"] + get_categories(uid, "income"), key="inc_filter_cat")
    df_inc = get_incomes(uid, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), None if cat_f=="All" else cat_f)
    if not df_inc.empty:
        st.dataframe(df_inc, use_container_width=True)
        st.download_button("Download incomes CSV", df_inc.to_csv(index=False).encode("utf-8"), "incomes.csv", "text/csv")
    else:
        st.info("No incomes for selected filters.")

# ---------- Categories tab ----------
with tabs[3]:
    st.subheader("Manage Categories")
    col1, col2 = st.columns(2)
    with col1:
        new_e = st.text_input("New expense category")
        if st.button("Add expense category"):
            if new_e.strip():
                add_category(uid, new_e.strip(), "expense"); st.success("Added")
            else: st.warning("Enter name")
    with col2:
        new_i = st.text_input("New income category")
        if st.button("Add income category"):
            if new_i.strip():
                add_category(uid, new_i.strip(), "income"); st.success("Added")
            else: st.warning("Enter name")
    st.write("Expense categories:", get_categories(uid, "expense"))
    st.write("Income categories:", get_categories(uid, "income"))

# ---------- Budgets tab ----------
with tabs[4]:
    st.subheader("Monthly & Category Budgets")
    mon = st.text_input("Month (YYYY-MM)", value=date.today().strftime("%Y-%m"), key="budget_month")
    total_b = st.number_input("Monthly Budget (total)", min_value=0.0, format="%.2f", key="budget_total")
    if st.button("Save monthly budget"):
        set_monthly_budget(uid, mon, float(total_b)); st.success("Saved")
    st.subheader("Category Budget")
    cat = st.selectbox("Category", get_categories(uid, "expense"))
    cat_b = st.number_input("Category budget", min_value=0.0, format="%.2f", key="cat_budget")
    if st.button("Save category budget"):
        set_category_budget(uid, mon, cat, float(cat_b)); st.success("Saved")
    cur_month = date.today().strftime("%Y-%m")
    mb = get_monthly_budget(uid, cur_month)
    st.write("This month total budget:", mb if mb else "Not set")
    cb = collection_to_df(db.collection("category_budgets"), filters=[("user_id","==",uid),("month","==",cur_month)])
    if not cb.empty:
        st.write("Category budgets (this month):")
        st.dataframe(cb[["category","budget"]])

# ---------- Reports tab ----------
with tabs[5]:
    st.subheader("PDF / Exports")
    sel_month = st.text_input("Report month (YYYY-MM)", value=date.today().strftime("%Y-%m"))
    if not _FPDF_AVAILABLE:
        st.warning("Install fpdf2 for PDF export: pip install fpdf2")
    else:
        if st.button("Generate PDF report"):
            try:
                out = generate_pdf(uid, sel_month)
                with open(out, "rb") as f:
                    st.download_button("Download PDF", f.read(), file_name=os.path.basename(out), mime="application/pdf")
                st.success("PDF generated")
            except Exception as e:
                st.error(f"PDF error: {e}")
    st.markdown("---")
    exp_all = get_expenses(uid)
    inc_all = get_incomes(uid)
    if not exp_all.empty:
        st.download_button("Export all expenses CSV", exp_all.to_csv(index=False).encode("utf-8"), "expenses_all.csv")
    if not inc_all.empty:
        st.download_button("Export all incomes CSV", inc_all.to_csv(index=False).encode("utf-8"), "incomes_all.csv")

# ---------- Settings ----------
with tabs[6]:
    st.subheader("Settings")
    st.write("Firestore project status:", "Connected" if FIRESTORE_OK else "Not connected")
    st.write("Reports folder:", REPORTS_DIR)
    st.markdown("---")
    st.write("Note: Resetting or deleting Firestore collections is destructive and not provided here.")
    st.write("To reset data for development, either delete documents in Firebase Console or implement a safe reset script locally.")

# End of app
