"""作废与当前有效指针的端到端行为测试（SQLite 内存库 + TestClient）。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Candidate, Hall, PaperSet, PLAN_VOID, SeatPlan


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    hall = Hall(code="H101", name="一号考室", rows=5, cols=6, min_manhattan=2)
    db.add(hall); db.flush()
    p1 = PaperSet(code="P-A", title="A 卷"); db.add(p1); db.flush()
    names = ["陈一", "李二", "张三", "赵四", "钱五", "孙六"]
    for i, name in enumerate(names):
        db.add(Candidate(hall_id=hall.id, name=name, ticket_no=f"T{2026001+i}", paper_id=p1.id))
    db.commit()
    yield db
    db.close()


@pytest.fixture()
def client(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---- 无方案：三口为空，且绝不自动生成 ----

def test_latest_empty_does_not_autogenerate(client, db_session):
    res = client.get("/api/seating/latest?hall_id=1")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] is None and body["void"] is True
    assert body["assignments"] == [] and body["violations"] == []
    assert body["stats"] == {"seated": 0, "unplaced": 0, "violations": 0, "capacity": 30}
    assert db_session.scalar(select(func.count()).select_from(SeatPlan)) == 0

    v = client.get("/api/seating/violations?hall_id=1").json()
    assert v["plan_id"] is None and v["violations"] == [] and v["unplaced"] == []
    s = client.get("/api/seating/stats?hall_id=1").json()
    assert s["plan_id"] is None and s["seated"] == 0


# ---- 种子连排两张，作废最新一张：图/违规/统计回到第一张 ----

def test_void_latest_falls_back_to_previous(client, db_session):
    plan1 = client.post("/api/seating/run?hall_id=1").json()
    plan2 = client.post("/api/seating/run?hall_id=1").json()
    assert plan2["id"] > plan1["id"]
    assert client.get("/api/seating/latest?hall_id=1").json()["id"] == plan2["id"]

    res = client.post(f"/api/seating/{plan2['id']}/void?hall_id=1")
    assert res.status_code == 200
    cur = res.json()["current"]
    assert cur["id"] == plan1["id"] and cur["void"] is False

    latest = client.get("/api/seating/latest?hall_id=1").json()
    assert latest["id"] == plan1["id"]
    assert latest["assignments"] == plan1["assignments"]  # 图回到第一张
    assert latest["stats"] == plan1["stats"]
    assert client.get("/api/seating/violations?hall_id=1").json()["plan_id"] == plan1["id"]
    assert client.get("/api/seating/stats?hall_id=1").json()["plan_id"] == plan1["id"]

    # 已作废案留档但不再被当成最新
    voided = db_session.get(SeatPlan, plan2["id"])
    assert voided.status == PLAN_VOID and voided.voided_at is not None


# ---- 再对已作废案调座/作废：拒绝 ----

def test_swapping_or_revoiding_void_plan_rejected(client):
    plan1 = client.post("/api/seating/run?hall_id=1").json()
    plan2 = client.post("/api/seating/run?hall_id=1").json()
    client.post(f"/api/seating/{plan2['id']}/void?hall_id=1")

    r = client.post(f"/api/seating/{plan2['id']}/void?hall_id=1")
    assert r.status_code == 409

    r = client.post("/api/seating/swap", json={"a_id": 1, "b_id": 2, "hall_id": 1, "plan_id": plan2["id"]})
    assert r.status_code == 409
    # 拒绝后指针仍是第一张
    assert client.get("/api/seating/latest?hall_id=1").json()["id"] == plan1["id"]


# ---- 全部作废：三口同时为空，且不会自动补一张 ----

def test_void_all_leaves_all_three_empty(client, db_session):
    plan1 = client.post("/api/seating/run?hall_id=1").json()
    client.post("/api/seating/run?hall_id=1")
    latest_id = client.get("/api/seating/latest?hall_id=1").json()["id"]
    client.post(f"/api/seating/{latest_id}/void?hall_id=1")
    res = client.post(f"/api/seating/{plan1['id']}/void?hall_id=1")
    assert res.json()["current"]["id"] is None

    assert client.get("/api/seating/latest?hall_id=1").json()["id"] is None
    assert client.get("/api/seating/violations?hall_id=1").json()["violations"] == []
    assert client.get("/api/seating/stats?hall_id=1").json()["seated"] == 0
    # 没有借读取动作偷偷重排
    assert db_session.scalar(select(func.count()).select_from(SeatPlan)) == 2

    # 只有显式 run 才能产生新方案
    plan3 = client.post("/api/seating/run?hall_id=1").json()
    assert plan3["id"] and plan3["void"] is False
    assert client.get("/api/seating/latest?hall_id=1").json()["id"] == plan3["id"]


# ---- 作废失败：指针与三页保持操作前 ----

def test_void_failure_keeps_state(client, monkeypatch):
    plan = client.post("/api/seating/run?hall_id=1").json()
    before_latest = client.get("/api/seating/latest?hall_id=1").json()["id"]

    def boom(self):
        raise RuntimeError("db down")
    monkeypatch.setattr("sqlalchemy.orm.Session.commit", boom)
    r = client.post(f"/api/seating/{plan['id']}/void?hall_id=1")
    assert r.status_code == 500
    monkeypatch.undo()

    assert client.get("/api/seating/latest?hall_id=1").json()["id"] == before_latest


def test_void_nonexistent_keeps_state(client):
    plan = client.post("/api/seating/run?hall_id=1").json()
    r = client.post("/api/seating/9999/void?hall_id=1")
    assert r.status_code == 404
    assert client.get("/api/seating/latest?hall_id=1").json()["id"] == plan["id"]


# ---- 当前有效方案允许调座；无有效方案拒绝 ----

def test_swap_on_active_plan_updates_only_current(client):
    plan1 = client.post("/api/seating/run?hall_id=1").json()
    p2 = client.post("/api/seating/run?hall_id=1").json()
    client.post(f"/api/seating/{p2['id']}/void?hall_id=1")  # 指针回到 plan1

    def pos(plan_body, cid):
        a = next(x for x in plan_body["assignments"] if x["candidate_id"] == cid)
        return a["row"], a["col"]

    r = client.post("/api/seating/swap", json={"a_id": 1, "b_id": 2, "hall_id": 1, "plan_id": plan1["id"]})
    assert r.status_code == 200
    after = r.json()
    assert pos(after, 1) == pos(plan1, 2) and pos(after, 2) == pos(plan1, 1)
    assert client.get("/api/seating/latest?hall_id=1").json()["id"] == plan1["id"]

    # 全部作废后再调座：拒绝
    client.post(f"/api/seating/{plan1['id']}/void?hall_id=1")
    r = client.post("/api/seating/swap", json={"a_id": 1, "b_id": 2, "hall_id": 1})
    assert r.status_code == 409

    # 输入校验
    r = client.post("/api/seating/swap", json={"a_id": 1, "b_id": 1, "hall_id": 1})
    assert r.status_code == 400
    r = client.post("/api/seating/swap", json={"a_id": 1, "b_id": 999, "hall_id": 1})
    assert r.status_code in (404, 409)


# ---- 作废不得改动考生名单与考室网格 ----

def test_void_does_not_touch_candidates_or_hall(client, db_session):
    before_cands = db_session.scalar(select(func.count()).select_from(Candidate))
    hall_before = db_session.get(Hall, 1)
    dims = (hall_before.rows, hall_before.cols, hall_before.min_manhattan)
    tickets = sorted(c.ticket_no for c in db_session.scalars(select(Candidate)).all())

    p1 = client.post("/api/seating/run?hall_id=1").json()
    p2 = client.post("/api/seating/run?hall_id=1").json()
    client.post(f"/api/seating/{p2['id']}/void?hall_id=1")
    client.post(f"/api/seating/{p1['id']}/void?hall_id=1")

    assert db_session.scalar(select(func.count()).select_from(Candidate)) == before_cands
    assert sorted(c.ticket_no for c in db_session.scalars(select(Candidate)).all()) == tickets
    h = db_session.get(Hall, 1)
    assert (h.rows, h.cols, h.min_manhattan) == dims
