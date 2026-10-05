from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    """Lightweight additive migration for pre-existing databases (no Alembic).

    Only ever ADDS missing columns/tables; candidate and hall data are untouched.
    """
    inspector = inspect(engine)
    if "seat_plans" in inspector.get_table_names():
        existing = {col["name"] for col in inspector.get_columns("seat_plans")}
        ddl = []
        if "status" not in existing:
            ddl.append("ALTER TABLE seat_plans ADD COLUMN status VARCHAR(16) "
                       "NOT NULL DEFAULT 'active'")
            ddl.append("CREATE INDEX IF NOT EXISTS ix_seat_plans_status ON seat_plans (status)")
        if "voided_at" not in existing:
            ddl.append("ALTER TABLE seat_plans ADD COLUMN voided_at TIMESTAMP")
        if ddl:
            with engine.begin() as conn:
                for stmt in ddl:
                    conn.execute(text(stmt))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
