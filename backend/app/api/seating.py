import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Candidate, Hall, SeatPlan
from app.services.plan_pointer import clear_pointer, get_active_plan, latest_valid_plan, set_pointer
from app.services.seat_engine import (
    SeatAssign,
    find_violations,
    place_candidates,
    plan_to_dict,
    swap_candidates,
)

router = APIRouter(prefix="/seating", tags=["seating"])


def _build_plan(db: Session, hall: Hall) -> dict:
    cands = [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
             for c in db.scalars(
                 select(Candidate).where(Candidate.hall_id == hall.id).order_by(Candidate.id)).all()]
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    return result


def _empty_payload(hall: Hall) -> dict:
    """All three pages (map/violations/stats) read this when no plan is valid."""
    return {
        "id": None,
        "empty": True,
        "rows": hall.rows,
        "cols": hall.cols,
        "assignments": [],
        "unplaced": [],
        "violations": [],
        "stats": {"seated": 0, "unplaced": 0, "violations": 0, "capacity": hall.rows * hall.cols},
        "hall": {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan},
    }


def _plan_payload(plan: SeatPlan) -> dict:
    return {"id": plan.id, "empty": False, **json.loads(plan.result_json)}


def _latest_payload(db: Session, hall: Hall) -> dict:
    plan = get_active_plan(db, hall.id)
    return _plan_payload(plan) if plan is not None else _empty_payload(hall)


class VoidIn(BaseModel):
    # When omitted, the current (pointer) plan is voided. A specific id that is
    # not the current plan is rejected — voided plans cannot be voided again.
    plan_id: int | None = None


class SwapIn(BaseModel):
    a_id: int
    b_id: int
    # Must equal the current plan id when given; any stale/voided id is refused.
    plan_id: int | None = None


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    """Explicit user action only: build a NEW plan and move the pointer to it."""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    result = _build_plan(db, hall)
    try:
        plan = SeatPlan(hall_id=hall_id, created_at=datetime.utcnow(),
                        voided=False, result_json=json.dumps(result, ensure_ascii=False))
        db.add(plan)
        db.flush()
        set_pointer(db, hall_id, plan.id)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, "排座写入失败，当前方案保持不变")
    db.refresh(plan)
    return _plan_payload(plan)


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    """Read-only: return whatever the pointer names. Never generates a plan."""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    return _latest_payload(db, hall)


@router.post("/void")
def void_plan(body: VoidIn, hall_id: int = 1, db: Session = Depends(get_db)):
    """Void the current plan and switch the pointer to the previous valid one,
    or clear the pointer if none remains. Never creates a replacement plan."""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")

    active = get_active_plan(db, hall_id)
    if active is None:
        raise HTTPException(409, "当前没有有效方案，无可作废方案")
    if body.plan_id is not None and body.plan_id != active.id:
        target = db.get(SeatPlan, body.plan_id)
        if target is not None and target.voided:
            raise HTTPException(409, "该方案已作废，不能再次作废")
        raise HTTPException(409, "只能作废当前有效方案")

    try:
        active.voided = True
        active.voided_at = datetime.utcnow()
        db.flush()

        previous = latest_valid_plan(db, hall_id)
        if previous is not None:
            set_pointer(db, hall_id, previous.id)
        else:
            clear_pointer(db, hall_id)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, "作废失败，当前方案与指针保持不变")

    db.refresh(active)
    if previous is not None:
        db.refresh(previous)
        payload = _plan_payload(previous)
    else:
        payload = _empty_payload(hall)
    return {"voided_id": active.id, "active_plan_id": (previous.id if previous else None),
            "plan": payload}


@router.post("/swap")
def swap_seats(body: SwapIn, hall_id: int = 1, db: Session = Depends(get_db)):
    """Swap two candidates within the CURRENT plan only.

    Writes go back into the same plan row (same id) — a voided or non-current
    plan is never written, and no new plan row is ever created by a swap.
    """
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    plan = get_active_plan(db, hall_id)
    if plan is None:
        raise HTTPException(409, "当前没有有效方案，无法对调座位")
    if body.plan_id is not None and body.plan_id != plan.id:
        raise HTTPException(409, "方案已作废或不是当前方案，禁止对调")

    try:
        data = json.loads(plan.result_json)
        assigns = [SeatAssign(**a) for a in data.get("assignments", [])]
        try:
            swap_candidates(assigns, body.a_id, body.b_id)
        except LookupError:
            raise HTTPException(404, "考生不在当前方案中")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
        unplaced = data.get("unplaced", [])
        result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
        result["hall"] = data.get("hall", {"id": hall.id, "name": hall.name,
                                           "min_manhattan": hall.min_manhattan})
        plan.result_json = json.dumps(result, ensure_ascii=False)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "对调失败，当前方案保持不变")
    db.refresh(plan)
    return _plan_payload(plan)


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    data = _latest_payload(db, hall)
    return {"hall_id": hall_id, "active_plan_id": data.get("id"),
            "empty": data.get("empty", False),
            "violations": data.get("violations", []),
            "unplaced": data.get("unplaced", [])}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    data = _latest_payload(db, hall)
    return {"hall_id": hall_id, "active_plan_id": data.get("id"),
            "empty": data.get("empty", False), **data.get("stats", {})}
