from fastapi.testclient import TestClient

from interviewer.contracts import ErrorEnvelope


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
