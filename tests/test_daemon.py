import pytest
from fastapi.testclient import TestClient
from titan.daemon import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestDaemonBasics:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["version"] == "12.0"

    def test_diagnostics_includes_version(self, client):
        r = client.get("/api/v1/diagnostics")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == "12.0"


class TestStateEndpoint:
    def test_get_state_with_key(self, client):
        r = client.get("/api/v1/state", params={"key": "any_key"})
        assert r.status_code == 200
        body = r.json()
        assert body["key"] == "any_key"
        assert "value" in body
        assert "found" in body

    def test_get_state_missing_key_returns_400(self, client):
        r = client.get("/api/v1/state")
        assert r.status_code in (400, 422)

    def test_get_state_empty_key_returns_400(self, client):
        r = client.get("/api/v1/state", params={"key": ""})
        assert r.status_code in (400, 422)


class TestDigitalTwinTimeline:
    def test_default_24_hours(self, client):
        r = client.get("/api/v1/digital_twin/timeline")
        assert r.status_code == 200
        assert r.json()["hours"] == 24

    def test_custom_hours(self, client):
        r = client.get("/api/v1/digital_twin/timeline", params={"hours": 48})
        assert r.status_code == 200
        assert r.json()["hours"] == 48

    def test_hours_must_be_positive(self, client):
        r = client.get("/api/v1/digital_twin/timeline", params={"hours": 0})
        assert r.status_code == 422

    def test_hours_too_large_rejected(self, client):
        r = client.get("/api/v1/digital_twin/timeline", params={"hours": 100000})
        assert r.status_code == 422


class TestFailurePatterns:
    def test_default_min_occurrences(self, client):
        r = client.get("/api/v1/knowledge/failure_patterns")
        assert r.status_code == 200
        assert r.json()["min_occurrences"] == 15

    def test_custom_min_occurrences(self, client):
        r = client.get("/api/v1/knowledge/failure_patterns", params={"min_occurrences": 5})
        assert r.status_code == 200
        assert r.json()["min_occurrences"] == 5

    def test_min_occurrences_below_one_rejected(self, client):
        r = client.get("/api/v1/knowledge/failure_patterns", params={"min_occurrences": 0})
        assert r.status_code == 422


class TestPOSTEndpointsUseBody:
    """Regression: previously all POSTs took their params as query string.
    Now POSTs that carry data use a JSON body."""

    def test_hardware_analyze_requires_body(self, client):
        r = client.post("/api/v1/hardware/analyze")
        assert r.status_code == 422

    def test_hardware_analyze_with_body(self, client):
        r = client.post("/api/v1/hardware/analyze", json={"path": "/tmp/foo.dts"})
        assert r.status_code == 200
        assert "queued" in r.json()["status"].lower()

    def test_build_failure_requires_body(self, client):
        r = client.post("/api/v1/build/failure")
        assert r.status_code == 422

    def test_build_failure_with_body(self, client):
        r = client.post("/api/v1/build/failure", json={"log_path": "/tmp/build.log"})
        assert r.status_code == 200
        assert r.json()["status"].startswith("Build failure")

    def test_snapshot_requires_body(self, client):
        r = client.post("/api/v1/digital_twin/snapshot")
        assert r.status_code == 422

    def test_snapshot_with_body(self, client):
        r = client.post("/api/v1/digital_twin/snapshot", json={"snapshot_id": "snap-1", "note": "pre-upgrade"})
        assert r.status_code == 200
        assert "snap-1" in r.json()["status"]

    def test_learn_requires_body(self, client):
        r = client.post("/api/v1/knowledge/learn")
        assert r.status_code == 422

    def test_learn_with_body(self, client):
        r = client.post("/api/v1/knowledge/learn",
                       json={"problem_signature": "YOC-004", "success": True, "notes": "ok"})
        assert r.status_code == 200
        body = r.json()
        assert body["problem_signature"] == "YOC-004"
        assert body["success"] is True

    def test_analyze_requires_query(self, client):
        r = client.post("/api/v1/analyze", json={})
        assert r.status_code == 422

    def test_analyze_with_body(self, client):
        r = client.post("/api/v1/analyze", json={"query": "porque o openssl falhou?"})
        assert r.status_code == 200
        assert r.json()["event_type"] == "user_query"


class TestExplain404:
    def test_explain_missing_record_returns_404(self, client):
        r = client.get("/api/v1/knowledge/explain", params={"problem_signature": "YOC-DOES-NOT-EXIST"})
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()
