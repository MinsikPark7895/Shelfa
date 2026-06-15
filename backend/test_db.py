from db.database import SessionLocal
from db.models import Book
db = SessionLocal()
books = db.query(Book).filter(Book.status == "AVAILABLE").all()
for b in books:
    print(b.title, b.author, b.shelf_location)
