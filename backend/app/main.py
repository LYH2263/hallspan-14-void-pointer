from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.plan_pointer import backfill_pointers
from app.services.seed import seed_if_empty


def ensure_schema_columns() -> None:
    """Upgrade databases created before voiding existed (no alembic here)."""
    inspector = inspect(engine)
    if "seat_plans" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("seat_plans")}
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if "voided" not in existing:
            bool_type = "BOOLEAN" if dialect == "postgresql" else "BOOLEAN"
            conn.execute(text(
                f"ALTER TABLE seat_plans ADD COLUMN voided {bool_type} "
                f"NOT NULL DEFAULT {'FALSE' if dialect == 'postgresql' else '0'}"
            ))
        if "voided_at" not in existing:
            ts_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
            conn.execute(text(
                f"ALTER TABLE seat_plans ADD COLUMN voided_at {ts_type}"
            ))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema_columns()
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    db = SessionLocal()
    try:
        backfill_pointers(db)
    finally:
        db.close()
    yield


app = FastAPI(title="HallSpan", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
