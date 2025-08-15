# create_tables.py
from finance.db import Base, engine
from finance import models

Base.metadata.create_all(bind=engine)
print("✅ Tables created successfully!")
