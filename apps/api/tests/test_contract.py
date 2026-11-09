from fastapi.testclient import TestClient

from interviewer.contracts import ErrorEnvelope
from interviewer.main import create_app
from interviewer.settings import Settings


def test_production_https_login_is_separate_and_rejects_cross_origin() -> None:
    origin = "https://interview.example.test"
    settings = Settings(sqlite_path=":memory:", environment="production", demo=False, app_base_url=origin,
                        secret="fixture-" * 8, recruiter_password="recruiter-fixture", admin_password="admin-only-fixture")
    with TestClient(create_app(settings), base_url=origin) as client:
        for invalid in ["", "错误访问码", settings.admin_password]:
            assert client.post("/api/auth/login", json={"accessCode": invalid}, headers={"Origin": origin}).status_code == 401
        assert client.post("/api/auth/login", json={"accessCode": settings.recruiter_password},
                           headers={"Origin": "https://other.example.test"}).status_code == 401
        recruiter = client.post("/api/auth/login", json={"accessCode": settings.recruiter_password}, headers={"Origin": origin})
        assert recruiter.status_code == 200
        assert all(flag in recruiter.headers["set-cookie"] for flag in ["HttpOnly", "Secure", "SameSite=strict"])
        assert client.get("/api/jobs").status_code == 200
        assert client.get("/api/admin/interviews").status_code == 403
        assert client.post("/api/admin/login", json={"accessCode": settings.recruiter_password},
                           headers={"Origin": origin}).status_code == 401
        assert client.post("/api/admin/login", json={"accessCode": settings.admin_password},
                           headers={"Origin": origin}).status_code == 200
        assert client.get("/api/admin/interviews").status_code == 200


def test_openapi_documents_auth_errors_and_streaming(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    assert len(schema["paths"]) >= 29
    assert schema["paths"]["/api/interviews/{interview_id}/turns"]["post"]["security"] == [{"CandidateBearer": []}]
    assert "text/event-stream" in schema["paths"]["/api/interviews/{interview_id}/turns"]["post"]["responses"]["200"]["content"]
    for methods in schema["paths"].values():
        for operation in methods.values():
            assert "422" not in operation["responses"]
            assert "400" in operation["responses"] and "security" in operation

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                target = schema
                for key in str(value["$ref"]).removeprefix("#/").split("/"):
                    target = target[key]
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(schema)
    ErrorEnvelope.model_validate(client.get("/api/jobs").json())
