"""Real PG16 parity runs only against an explicitly supplied disposable CI database."""
import os

import pytest
from fastapi.testclient import TestClient

from conftest import STRONG, begin, invitation
from interviewer.contracts import ReportDocument
from interviewer.main import create_app
from interviewer.settings import Settings


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires disposable Postgres16")
def test_postgres_full_flow_and_erasure() -> None:
    settings = Settings(database_url=os.environ["TEST_DATABASE_URL"], secret="fixture-" * 8, admin_key="fixture-admin")
    with TestClient(create_app(settings)) as client:
        created, person = invitation(client, "graduate_campus")
        identity, headers = str(created["interviewId"]), begin(client, created)
        for _ in range(int(str(created["questionCount"]))):
            assert client.post(f"/api/interviews/{identity}/turns", headers=headers, json={"action": "answer", "content": STRONG}).status_code == 200
        assert client.post(f"/api/interviews/{identity}/finish", headers=headers, json={}).status_code == 200
        response = client.post(f"/api/interviews/{identity}/score", json={})
        assert response.status_code == 200, response.text
        report = ReportDocument.model_validate(response.json())
        assert len(report.dimensions) == 4 and all(row.evidence_ids for row in report.dimensions)
        removed = client.request("DELETE", f"/api/candidates/{person['id']}", headers={"Authorization": "Bearer fixture-admin"},
                                 json={"confirmCandidateId": person["id"], "reason": "清除隔离CI合成测试数据"})
        assert removed.status_code == 200, removed.text
        assert client.get(f"/api/interviews/{identity}/state", headers=headers).status_code == 401
