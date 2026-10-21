import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/users.db")

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def migrate():
    """Add columns introduced after the first deploy to an existing users table."""
    import secrets

    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "unsubscribe_token" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN unsubscribe_token VARCHAR"))
        # Backfill tokens for users created before the column existed
        ids = conn.execute(
            text("SELECT id FROM users WHERE unsubscribe_token IS NULL")
        ).scalars().all()
        for user_id in ids:
            conn.execute(
                text("UPDATE users SET unsubscribe_token = :t WHERE id = :id"),
                {"t": secrets.token_urlsafe(32), "id": user_id},
            )
