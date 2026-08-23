from sqlmodel import SQLModel, create_engine
import os

db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(db_dir, exist_ok=True)
db_path = os.path.join(db_dir, "database.db")
sqlite_url = f"sqlite:///{db_path}"

engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
