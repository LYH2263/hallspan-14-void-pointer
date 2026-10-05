import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate, Hall, PLAN_VOID, SeatPlan
from app.services.seat_engine import (
    SeatAssign, find_violations, place_candidates, plan_to_dict,
)
router = APIRouter(prefix="/seating", tags=["seating"])


def _get_hall(db: Session, hall_id: int) -> Hall:
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    return hall


def _active_plan(db: Session, hall_id: int) -> SeatPlan | None:
    """当前有效指针：该考室下最新一张仍有效的方案（已作废案永远不入选）。"""
    return db.scalars(
        select(SeatPlan)
        .where(SeatPlan.hall_id == hall_id, SeatPlan.status != PLAN_VOID)
        .order_by(SeatPlan.id.desc())
    ).first()


def _empty_result(hall: Hall) -> dict:
    """三口同时为空时返回的空壳——只描述网格尺寸，不含任何排座结果。"""
    return {
        "id": None,
        "rows": hall.rows,
        "cols": hall.cols,
        "assignments": [],
        "unplaced": [],
        "violations": [],
        "stats": {"seated": 0, "unplaced": 0, "violations": 0, "capacity": hall.rows * hall.cols},
        "hall": {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan},
        "void": True,
    }


def _plan_payload(plan: SeatPlan) -> dict:
    data = json.loads(plan.result_json)
    return {"id": plan.id, "void": False, **data}


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = _get_hall(db, hall_id)
    cands = [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
             for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id)).all()]
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    plan = SeatPlan(hall_id=hall_id, created_at=datetime.utcnow(),
                    result_json=json.dumps(result, ensure_ascii=False))
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _plan_payload(plan)


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = _get_hall(db, hall_id)
    plan = _active_plan(db, hall_id)
    # 无有效方案：返回空壳，绝不自动重排（「切指针」与「作废即重排」互斥）
    if not plan:
        return _empty_result(hall)
    return _plan_payload(plan)


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "plan_id": data.get("id"),
            "violations": data.get("violations", []), "unplaced": data.get("unplaced", [])}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "plan_id": data.get("id"), **data.get("stats", {})}


@router.post("/{plan_id}/void")
def void_plan(plan_id: int, hall_id: int = 1, db: Session = Depends(get_db)):
    """作废指定方案。成功后指针切到上一张仍有效的方案；没有则三口同时为空。

    作废只翻转状态，不删数据、不动考生名单与考室网格，也不会自动生成新方案。
    """
    hall = _get_hall(db, hall_id)
    plan = db.get(SeatPlan, plan_id)
    if not plan or plan.hall_id != hall_id:
        raise HTTPException(404, "方案不存在")
    if plan.status == PLAN_VOID:
        raise HTTPException(409, "该方案已作废，不能重复作废")
    plan.status = PLAN_VOID
    plan.voided_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()  # 作废失败：指针与三页保持操作前
        raise HTTPException(500, "作废失败，状态未改变")
    current = _active_plan(db, hall_id)
    return {
        "voided_id": plan_id,
        "current": _plan_payload(current) if current else _empty_result(hall),
    }


class SwapBody(BaseModel):
    a_id: int
    b_id: int
    hall_id: int = 1
    plan_id: int | None = None  # 传入时必须是当前有效方案；指向已作废案则拒绝


@router.post("/swap")
def swap_seats(body: SwapBody, db: Session = Depends(get_db)):
    """对调当前有效方案中两名考生的座位，并就地重算违规与统计。

    已作废案禁止调座；无有效方案时拒绝。写入只落在当前指针指向的方案上。
    """
    if body.a_id == body.b_id:
        raise HTTPException(400, "不能与自身对调")
    hall = _get_hall(db, body.hall_id)
    if body.plan_id is not None:
        target = db.get(SeatPlan, body.plan_id)
        if not target or target.hall_id != body.hall_id:
            raise HTTPException(404, "方案不存在")
        if target.status == PLAN_VOID:
            raise HTTPException(409, "方案已作废，禁止对已作废案调座")
    plan = _active_plan(db, body.hall_id)
    if not plan:
        raise HTTPException(409, "当前无有效方案，无法调座")
    if body.plan_id is not None and body.plan_id != plan.id:
        raise HTTPException(409, "只能对当前有效方案调座")

    data = json.loads(plan.result_json)
    assignments = data.get("assignments", [])
    idx: dict[int, int] = {a["candidate_id"]: i for i, a in enumerate(assignments)}
    if body.a_id not in idx or body.b_id not in idx:
        raise HTTPException(404, "考生不在当前有效方案的已排座位中")
    ai, bi = idx[body.a_id], idx[body.b_id]
    assignments[ai]["row"], assignments[bi]["row"] = assignments[bi]["row"], assignments[ai]["row"]
    assignments[ai]["col"], assignments[bi]["col"] = assignments[bi]["col"], assignments[ai]["col"]

    min_dist = data.get("hall", {}).get("min_manhattan", hall.min_manhattan)
    assigns = [SeatAssign(**a) for a in assignments]
    viols = find_violations(data["rows"], data["cols"], min_dist, assigns)
    data["violations"] = [
        {"kind": v.kind, "a_id": v.a_id, "b_id": v.b_id, "detail": v.detail} for v in viols
    ]
    data["stats"] = {
        "seated": len(assignments),
        "unplaced": len(data.get("unplaced", [])),
        "violations": len(viols),
        "capacity": data["rows"] * data["cols"],
    }
    plan.result_json = json.dumps(data, ensure_ascii=False)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, "调座失败，状态未改变")
    return _plan_payload(plan)
