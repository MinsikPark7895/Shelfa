from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql://shelfa_user:shelfa_password@localhost:5432/shelfa_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

try:
    db = SessionLocal()
    result = db.execute("SELECT id, title, shelf_location FROM books;")
    for row in result:
        print(f"ID: {row[0]}, Title: {row[1]}, Location: {row[2]}")
    print("Success")
except Exception as e:
    print(f"Error: {e}")
finally:
    db.close()
