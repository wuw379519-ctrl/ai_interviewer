from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import httpx
from fastapi.testclient import TestClient

from interviewer.contracts import Object, json_object
from interviewer.main import create_app
from interviewer.settings import Settings
from interviewer.settings import ROOT

STRONG = "我主导研究模块，个人负责核心实现和回归实验。我与同学沟通解决分歧并达成一致，将耗时降低40%，把验证机制复用到多个项目。"


@pytest.fixture(autouse=True)
def forbid_real_http_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(_self: httpx.HTTPTransport, _request: httpx.Request) -> httpx.Response:
        raise AssertionError("Real HTTP is forbidden in tests; use an explicit mock transport")

    async def blocked_async(_self: httpx.AsyncHTTPTransport, _request: httpx.Request) -> httpx.Response:
        raise AssertionError("Real HTTP is forbidden in tests; use an explicit mock transport")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked_async)


@pytest.fixture
def tmp_path() -> Path:
    # The desktop execution sandbox does not grant writes to the system pytest temp directory.
    # Use a fresh, ignored workspace directory; never delete an existing directory.
    target = ROOT / ".data" / "python-tests" / str(uuid4())
    assert target.resolve().is_relative_to((ROOT / ".data").resolve())
    target.mkdir(parents=True, exist_ok=False)
    return target


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(sqlite_path=":memory:", secret="fixture-" * 8,
                                       admin_key="fixture-admin", recruiter_key="fixture-recruiter"))) as value:
        yield value


def invitation(client: TestClient, track: str = "general", mode: str = "text", camera: bool = False) -> tuple[Object, Object]:
    assert client.post("/api/auth/login", json={}).status_code == 200
    response = client.post("/api/jobs", json={"title": "合成研发岗位" + uuid4().hex[:5], "recruitmentTrack": track,
                                            "jdText": "面向研究生的研发与分析岗位，负责实验系统实现、质量验证、协作与学习，以量化结果和个人贡献说明任务成效。"})
    assert response.status_code == 201, response.text
    job = json_object(response.json())
    response = client.post(f"/api/jobs/{job['id']}/competencies:extract", json={})
    assert response.status_code == 200, response.text
    dimensions = json_object(response.json())
    assert client.patch(f"/api/jobs/{job['id']}/competencies", json={"competencies": dimensions["competencies"]}).status_code == 200
    person = json_object(client.post("/api/candidates", json={"jobId": job["id"], "fullName": "合成候选人"}).json())
    response = client.post(f"/api/candidates/{person['id']}/resume", json={"text": "技能Python与SQL；项目：我主导实验模块，个人负责实现和验证，将处理耗时降低30%，协调团队分歧并复用验证机制。"})
    assert response.status_code == 201, response.text
    response = client.post("/api/interviews", json={"jobId": job["id"], "candidateId": person["id"], "durationMinutes": 15,
                                                   "mode": mode, "cameraRequired": camera})
    assert response.status_code == 201, response.text
    return json_object(response.json()), person


def begin(client: TestClient, created: Object) -> dict[str, str]:
    identity = str(created["interviewId"])
    headers = {"Authorization": "Bearer " + str(created["inviteToken"])}
    state = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    assert client.post(f"/api/interviews/{identity}/consent", headers=headers,
                       json={"accepted": True, "consentVersion": state["consentVersion"]}).status_code == 200
    response = client.post(f"/api/interviews/{identity}/start", headers=headers, json={})
    assert response.status_code == 200, response.text
    return headers
