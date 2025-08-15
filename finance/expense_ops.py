from datetime import date
from sqlalchemy.orm import sessionmaker
from .db import engine
from .models import Expense

Session = sessionmaker(bind=engine)

def add_expense(user_id: int, expense_date: date, amount: float, category: str, description: str):
    session = Session()
    try:
        new_expense = Expense(
            user_id=user_id,
            date=expense_date,
            amount=amount,
            category=category,
            description=description
        )
        session.add(new_expense)
        session.commit()
        return True
    except Exception as e:
        print("Error adding expense:", e)
        session.rollback()
        return False
    finally:
        session.close()
