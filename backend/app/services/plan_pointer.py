"""Current-plan pointer: exactly one valid plan per hall, possibly none.

The pointer is the *only* thing map / violations / stats read from. Voiding a
plan moves the pointer (or clears it); it must never generate a new plan.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import ActivePlan, Hall, SeatPlan


def latest_valid_plan(db: Session, hall_id: int) -> SeatPlan | None:
    """Most recent non-voided plan of the hall, regardless of the pointer."""
    return db.scalars(
        select(SeatPlan)
        .where(SeatPlan.hall_id == hall_id, SeatPlan.voided.is_(False))
        .order_by(SeatPlan.id.desc())
    ).first()


def get_active_plan(db: Session, hall_id: int) -> SeatPlan | None:
    """Plan the pointer currently names — None if no pointer or it is stale.

    A stale pointer (points at a voided/missing plan) is treated as empty,
    never repaired by a read and never backfilled with a fresh plan.
    """
    row = db.get(ActivePlan, hall_id)
    if row is None:
        return None
    plan = db.get(SeatPlan, row.plan_id)
    if plan is None or plan.voided or plan.hall_id != hall_id:
        return None
    return plan


def set_pointer(db: Session, hall_id: int, plan_id: int) -> None:
    row = db.get(ActivePlan, hall_id)
    if row is None:
        db.add(ActivePlan(hall_id=hall_id, plan_id=plan_id))
    else:
        row.plan_id = plan_id
    db.flush()


def clear_pointer(db: Session, hall_id: int) -> None:
    row = db.get(ActivePlan, hall_id)
    if row is not None:
        db.delete(row)
    db.flush()


def backfill_pointers(db: Session) -> None:
    """Idempotent startup backfill: halls without a pointer get their newest
    non-voided plan (covers databases created before the pointer existed)."""
    for hall in db.scalars(select(Hall)).all():
        if db.get(ActivePlan, hall.id) is None:
            plan = latest_valid_plan(db, hall.id)
            if plan is not None:
                db.add(ActivePlan(hall_id=hall.id, plan_id=plan.id))
    db.commit()
