from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.models import ActivePlan, Candidate, Hall, SeatPlan


def run_twice(client):
    p1 = client.post("/api/seating/run?hall_id=1").json()
    p2 = client.post("/api/seating/run?hall_id=1").json()
    assert p1["id"] != p2["id"]
    return p1, p2


def plan_count(db) -> int:
    return db.query(SeatPlan).count()


def pointer_id(db, hall_id: int = 1):
    row = db.get(ActivePlan, hall_id)
    return None if row is None else row.plan_id


# ---- 核心需求：连排两张 → 作废最新 → 回到第一张 -----------------------------

def test_latest_does_not_auto_generate(client: TestClient):
    """全新考室：GET /latest 必须返回空态，绝不偷偷生成一张方案。"""
    r = client.get("/api/seating/latest?hall_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["empty"] is True
    assert body["id"] is None
    assert body["assignments"] == []
    assert body["violations"] == []
    db = SessionLocal()
    try:
        assert plan_count(db) == 0
        assert pointer_id(db) is None
    finally:
        db.close()


def test_seed_two_plans_then_void_latest_returns_first(client: TestClient):
    p1 = client.post("/api/seating/run?hall_id=1").json()
    p2 = client.post("/api/seating/run?hall_id=1").json()
    assert p1["id"] < p2["id"]

    # 指针指向最新一张
    assert client.get("/api/seating/latest").json()["id"] == p2["id"]

    r = client.post("/api/seating/void?hall_id=1", json={})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["voided_id"] == p2["id"]
    assert out["active_plan_id"] == p1["id"]

    # 三口立刻回到第一张
    latest = client.get("/api/seating/latest").json()
    assert latest["id"] == p1["id"]
    assert latest["empty"] is False
    viols = client.get("/api/seating/violations").json()
    assert viols["active_plan_id"] == p1["id"]
    stats = client.get("/api/seating/stats").json()
    assert stats["active_plan_id"] == p1["id"]
    assert stats["seated"] == len(latest["assignments"])

    # 图/统计内容确实等于第一张
    assert stats["seated"] == len(p1["assignments"])

    # 作废不得自动再生成新方案：仍然只有两行
    db = SessionLocal()
    try:
        assert plan_count(db) == 2
        assert pointer_id(db) == p1["id"]
        voided = db.get(SeatPlan, p2["id"])
        assert voided.voided is True
        assert voided.voided_at is not None
        first = db.get(SeatPlan, p1["id"])
        assert first.voided is False
    finally:
        db.close()


def test_void_again_clears_pointer_and_all_three_empty(client: TestClient):
    p1, _p2 = run_twice(client)
    client.post("/api/seating/void", json={})
    r = client.post("/api/seating/void", json={})
    assert r.status_code == 200
    assert r.json()["active_plan_id"] is None
    assert r.json()["plan"]["empty"] is True

    latest = client.get("/api/seating/latest").json()
    viols = client.get("/api/seating/violations").json()
    stats = client.get("/api/seating/stats").json()
    assert latest["empty"] is True and latest["assignments"] == []
    assert viols["empty"] is True and viols["violations"] == [] and viols["unplaced"] == []
    assert stats["empty"] is True and stats["seated"] == 0 and stats["violations"] == 0

    # 三张？不，始终只有两行——空态没有触发任何新方案
    db = SessionLocal()
    try:
        assert plan_count(db) == 2
        assert pointer_id(db) is None
        assert all(p.voided for p in db.query(SeatPlan).all())
    finally:
        db.close()


def test_void_with_no_active_plan_is_409_and_changes_nothing(client: TestClient):
    r = client.post("/api/seating/void", json={})
    assert r.status_code == 409
    db = SessionLocal()
    try:
        assert plan_count(db) == 0
        assert pointer_id(db) is None
    finally:
        db.close()
    # 三页仍是空态
    assert client.get("/api/seating/latest").json()["empty"] is True


# ---- 已作废方案禁止再对调、禁止被当成最新写入 -------------------------------

def _two_seated_ids(plan: dict):
    ids = [a["candidate_id"] for a in plan["assignments"]]
    assert len(ids) >= 2, "种子数据应至少排上两名考生"
    return ids[0], ids[1]


def test_swap_works_on_current_plan_same_row_id(client: TestClient):
    plan = client.post("/api/seating/run").json()
    a, b = _two_seated_ids(plan)
    before = {x["candidate_id"]: (x["row"], x["col"]) for x in plan["assignments"]}
    r = client.post("/api/seating/swap", json={"a_id": a, "b_id": b})
    assert r.status_code == 200, r.text
    after = r.json()
    # 对调写回同一张方案，不新增行、不改 id
    assert after["id"] == plan["id"]
    after_map = {x["candidate_id"]: (x["row"], x["col"]) for x in after["assignments"]}
    assert after_map[a] == before[b]
    assert after_map[b] == before[a]
    db = SessionLocal()
    try:
        assert plan_count(db) == 1
        assert pointer_id(db) == plan["id"]
    finally:
        db.close()


def test_swap_on_voided_plan_refused(client: TestClient):
    p1, p2 = run_twice(client)
    a, b = _two_seated_ids(p2)

    # 作废当前（第二张）→ 指针回到第一张；拿着旧方案 id 对调必须拒绝
    client.post("/api/seating/void", json={})
    r = client.post("/api/seating/swap", json={"a_id": a, "b_id": b, "plan_id": p2["id"]})
    assert r.status_code == 409

    # 不带 plan_id 也只会改当前第一张；尝试对只存在于第二张的考生（这里
    # 考生相同，改用 plan_id 断言隔离）：再次用旧 id 仍拒绝
    r2 = client.post("/api/seating/swap", json={"a_id": a, "b_id": b, "plan_id": p2["id"]})
    assert r2.status_code == 409

    # 第一张内容纹丝不动：统计与对调前一致
    latest = client.get("/api/seating/latest").json()
    assert latest["id"] == p1["id"]
    assert {(x["candidate_id"], x["row"], x["col"]) for x in latest["assignments"]} == \
           {(x["candidate_id"], x["row"], x["col"]) for x in p1["assignments"]}


def test_swap_with_no_active_plan_refused(client: TestClient):
    r = client.post("/api/seating/swap", json={"a_id": 1, "b_id": 2})
    assert r.status_code == 409
    db = SessionLocal()
    try:
        assert plan_count(db) == 0
    finally:
        db.close()


def test_swap_unknown_candidate_leaves_plan_untouched(client: TestClient):
    plan = client.post("/api/seating/run").json()
    a, _b = _two_seated_ids(plan)
    r = client.post("/api/seating/swap", json={"a_id": a, "b_id": 999999})
    assert r.status_code == 404
    latest = client.get("/api/seating/latest").json()
    assert latest["id"] == plan["id"]
    assert {(x["candidate_id"], x["row"], x["col"]) for x in latest["assignments"]} == \
           {(x["candidate_id"], x["row"], x["col"]) for x in plan["assignments"]}


# ---- 作废不得改动考生名单与考室网格 -----------------------------------------

def test_void_preserves_candidates_and_hall(client: TestClient):
    run_twice(client)
    client.post("/api/seating/void", json={})
    client.post("/api/seating/void", json={})

    db = SessionLocal()
    try:
        halls = db.query(Hall).count()
        cands = db.query(Candidate).count()
        hall = db.get(Hall, 1)
        assert halls == 1
        assert cands == 12
        assert (hall.rows, hall.cols, hall.min_manhattan) == (5, 6, 2)
    finally:
        db.close()

    cands_api = client.get("/api/candidates").json()
    assert len(cands_api) == 12
    halls_api = client.get("/api/halls").json()
    assert halls_api[0]["rows"] == 5 and halls_api[0]["cols"] == 6


# ---- 作废失败时指针与三页保持操作前（模拟提交失败） -------------------------

def test_failed_void_keeps_pointer_and_pages(monkeypatch, client: TestClient):
    p1, p2 = run_twice(client)  # 指针当前在第二张

    from app.api import seating as seating_api

    def boom(*_a, **_kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(seating_api, "set_pointer", boom)
    r = client.post("/api/seating/void", json={})
    assert r.status_code == 500

    latest = client.get("/api/seating/latest").json()
    assert latest["id"] == p2["id"]  # 指针保持操作前
    db = SessionLocal()
    try:
        assert pointer_id(db) == p2["id"]
        row = db.get(SeatPlan, p2["id"])
        assert row.voided is False  # 回滚，连 voided 标记都不留
    finally:
        db.close()


# ---- 手动 run 之后一切恢复 ---------------------------------------------------

def test_run_after_all_voided_recovers(client: TestClient):
    run_twice(client)
    client.post("/api/seating/void", json={})
    client.post("/api/seating/void", json={})
    assert client.get("/api/seating/latest").json()["empty"] is True

    p3 = client.post("/api/seating/run").json()
    assert p3["empty"] is False
    db = SessionLocal()
    try:
        assert pointer_id(db) == p3["id"]
        # 旧两张仍保持作废状态，没有被"复活"
        assert db.query(SeatPlan).filter(SeatPlan.voided.is_(False)).count() == 1
    finally:
        db.close()
