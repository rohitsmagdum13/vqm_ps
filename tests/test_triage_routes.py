"""Tests for the Path C triage routes.

Covers:
- Auth guarding: 401 when no token, 403 when role is VENDOR
- GET /triage/queue: 200 with serialized TriageQueueItem entries
- GET /triage/{query_id}: 404 (not found), 200 (success)
- POST /triage/{query_id}/review: 404, 409, 200 + reviewer_id from JWT
- Body validation: confidence_override bounds + reviewer_notes required
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.auth_middleware import AuthMiddleware
from api.routes.triage import router as triage_router
from models.triage import TriagePackage, TriageQueueItem
from services.auth import create_access_token, init_auth_service
from services.triage import (
    TriageAlreadyReviewedError,
    TriagePackageNotFoundError,
)


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _jwt_env(monkeypatch: pytest.MonkeyPatch):
    """Set JWT settings so create_access_token works in tests."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("SESSION_TIMEOUT_SECONDS", "1800")
    monkeypatch.setenv("TOKEN_REFRESH_THRESHOLD_SECONDS", "300")
    import config.settings as settings_module

    settings_module._settings = None
    yield
    settings_module._settings = None


@pytest.fixture
def mock_pg() -> AsyncMock:
    """Mock PostgresConnector for the auth service (JWT blacklist lookup)."""
    pg = AsyncMock()
    pg.fetchrow.return_value = None  # token not blacklisted
    init_auth_service(pg)
    return pg


@pytest.fixture
def mock_triage_service() -> AsyncMock:
    """AsyncMock TriageService pre-wired with sensible defaults."""
    svc = AsyncMock()
    svc.list_pending.return_value = []
    return svc


@pytest.fixture
def test_app(mock_pg: AsyncMock, mock_triage_service: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(triage_router)
    app.state.triage_service = mock_triage_service
    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


@pytest.fixture
def reviewer_headers(mock_pg: AsyncMock) -> dict[str, str]:
    """Bearer token headers for a REVIEWER role user."""
    token = create_access_token("reviewer-01", "REVIEWER", "hexaware")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(mock_pg: AsyncMock) -> dict[str, str]:
    """Bearer token headers for an ADMIN role user (allowed)."""
    token = create_access_token("admin-01", "ADMIN", "hexaware")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def vendor_headers(mock_pg: AsyncMock) -> dict[str, str]:
    """Bearer token headers for a VENDOR role user (not allowed)."""
    token = create_access_token("vendor-01", "VENDOR", "hexaware")
    return {"Authorization": f"Bearer {token}"}


def _sample_package() -> TriagePackage:
    from models.query import UnifiedQueryPayload
    from models.workflow import AnalysisResult

    return TriagePackage(
        query_id="VQ-2026-0099",
        correlation_id="corr-99",
        callback_token="test-token-abcdefghijklmno0123456789ab",
        original_query=UnifiedQueryPayload(
            query_id="VQ-2026-0099",
            correlation_id="corr-99",
            execution_id="exec-99",
            source="email",
            vendor_id="V-001",
            subject="Unusual request",
            body="Please help with this unusual ask.",
            received_at=datetime(2026, 4, 12, 10, 30, 0),
        ),
        analysis_result=AnalysisResult(
            intent_classification="UNKNOWN",
            urgency_level="MEDIUM",
            sentiment="NEUTRAL",
            confidence_score=0.40,
            suggested_category="general",
            analysis_duration_ms=1500,
            model_id="anthropic.claude-3-5-sonnet",
            tokens_in=1500,
            tokens_out=50,
        ),
        confidence_breakdown={"overall": 0.40, "threshold": 0.85},
        created_at=datetime(2026, 4, 12, 10, 30, 0),
    )


def _sample_queue_item() -> TriageQueueItem:
    return TriageQueueItem(
        query_id="VQ-2026-0099",
        correlation_id="corr-99",
        original_confidence=0.40,
        suggested_category="general",
        status="PENDING",
        created_at=datetime(2026, 4, 12, 10, 30, 0),
    )


def _valid_review_body() -> dict:
    return {
        "corrected_intent": "invoice_inquiry",
        "corrected_vendor_id": "V-001",
        "corrected_routing": "finance-ops",
        "confidence_override": 0.95,
        "reviewer_notes": "Human review: intent reclassified to invoice_inquiry.",
    }


# ---------------------------------------------------------------
# Auth guarding
# ---------------------------------------------------------------


class TestAuthGuards:
    """All three endpoints must reject missing / wrong-role callers."""

    def test_queue_requires_authentication(self, client: TestClient) -> None:
        resp = client.get("/triage/queue")
        assert resp.status_code == 401

    def test_detail_requires_authentication(self, client: TestClient) -> None:
        resp = client.get("/triage/VQ-2026-0099")
        assert resp.status_code == 401

    def test_review_requires_authentication(self, client: TestClient) -> None:
        resp = client.post("/triage/VQ-2026-0099/review", json=_valid_review_body())
        assert resp.status_code == 401

    def test_queue_rejects_vendor_role(
        self, client: TestClient, vendor_headers: dict[str, str],
    ) -> None:
        resp = client.get("/triage/queue", headers=vendor_headers)
        assert resp.status_code == 403
        assert "Reviewer or Admin" in resp.json()["detail"]

    def test_detail_rejects_vendor_role(
        self, client: TestClient, vendor_headers: dict[str, str],
    ) -> None:
        resp = client.get("/triage/VQ-2026-0099", headers=vendor_headers)
        assert resp.status_code == 403

    def test_review_rejects_vendor_role(
        self, client: TestClient, vendor_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/triage/VQ-2026-0099/review",
            headers=vendor_headers,
            json=_valid_review_body(),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------
# GET /triage/queue
# ---------------------------------------------------------------


class TestListQueue:
    def test_returns_serialized_items(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
        mock_triage_service: AsyncMock,
    ) -> None:
        mock_triage_service.list_pending.return_value = [_sample_queue_item()]

        resp = client.get("/triage/queue", headers=reviewer_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert "packages" in body
        assert len(body["packages"]) == 1
        assert body["packages"][0]["query_id"] == "VQ-2026-0099"
        assert body["packages"][0]["status"] == "PENDING"
        mock_triage_service.list_pending.assert_awaited_once()

    def test_admin_role_allowed(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        mock_triage_service: AsyncMock,
    ) -> None:
        mock_triage_service.list_pending.return_value = []
        resp = client.get("/triage/queue", headers=admin_headers)
        assert resp.status_code == 200


# ---------------------------------------------------------------
# GET /triage/{query_id}
# ---------------------------------------------------------------


class TestGetPackage:
    def test_returns_package_detail(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
        mock_triage_service: AsyncMock,
    ) -> None:
        mock_triage_service.get_package.return_value = _sample_package()

        resp = client.get("/triage/VQ-2026-0099", headers=reviewer_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["query_id"] == "VQ-2026-0099"
        assert body["callback_token"] == "test-token-abcdefghijklmno0123456789ab"
        assert body["analysis_result"]["confidence_score"] == 0.40

    def test_returns_404_when_not_found(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
        mock_triage_service: AsyncMock,
    ) -> None:
        mock_triage_service.get_package.side_effect = TriagePackageNotFoundError(
            "VQ-UNKNOWN",
        )

        resp = client.get("/triage/VQ-UNKNOWN", headers=reviewer_headers)

        assert resp.status_code == 404


# ---------------------------------------------------------------
# POST /triage/{query_id}/review
# ---------------------------------------------------------------


class TestSubmitReview:
    def test_happy_path_returns_200(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
        mock_triage_service: AsyncMock,
    ) -> None:
        mock_triage_service.submit_decision.return_value = {
            "status": "REVIEWED",
            "query_id": "VQ-2026-0099",
            "resume_method": "sqs",
        }

        resp = client.post(
            "/triage/VQ-2026-0099/review",
            headers=reviewer_headers,
            json=_valid_review_body(),
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "REVIEWED",
            "query_id": "VQ-2026-0099",
            "resume_method": "sqs",
        }

    def test_reviewer_id_comes_from_jwt_not_body(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
        mock_triage_service: AsyncMock,
    ) -> None:
        """Security: reviewer_id must be taken from JWT claim, not client-supplied."""
        mock_triage_service.submit_decision.return_value = {
            "status": "REVIEWED",
            "query_id": "VQ-2026-0099",
            "resume_method": "sqs",
        }

        body = _valid_review_body()
        # A client trying to spoof the reviewer_id shouldn't win
        body["reviewer_id"] = "attacker-9999"

        resp = client.post(
            "/triage/VQ-2026-0099/review",
            headers=reviewer_headers,
            json=body,
        )
        assert resp.status_code == 200

        # Service receives a ReviewerDecision whose reviewer_id comes from JWT sub
        decision = mock_triage_service.submit_decision.await_args.args[1]
        assert decision.reviewer_id == "reviewer-01"

    def test_returns_404_when_not_found(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
        mock_triage_service: AsyncMock,
    ) -> None:
        mock_triage_service.submit_decision.side_effect = TriagePackageNotFoundError(
            "VQ-UNKNOWN",
        )

        resp = client.post(
            "/triage/VQ-UNKNOWN/review",
            headers=reviewer_headers,
            json=_valid_review_body(),
        )
        assert resp.status_code == 404

    def test_returns_409_when_already_reviewed(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
        mock_triage_service: AsyncMock,
    ) -> None:
        mock_triage_service.submit_decision.side_effect = TriageAlreadyReviewedError(
            "VQ-2026-0099",
        )

        resp = client.post(
            "/triage/VQ-2026-0099/review",
            headers=reviewer_headers,
            json=_valid_review_body(),
        )
        assert resp.status_code == 409

    def test_rejects_confidence_override_above_range(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
    ) -> None:
        body = _valid_review_body()
        body["confidence_override"] = 1.5  # > 1.0 is invalid

        resp = client.post(
            "/triage/VQ-2026-0099/review",
            headers=reviewer_headers,
            json=body,
        )
        assert resp.status_code == 422

    def test_rejects_confidence_override_below_range(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
    ) -> None:
        body = _valid_review_body()
        body["confidence_override"] = -0.1

        resp = client.post(
            "/triage/VQ-2026-0099/review",
            headers=reviewer_headers,
            json=body,
        )
        assert resp.status_code == 422

    def test_requires_reviewer_notes(
        self,
        client: TestClient,
        reviewer_headers: dict[str, str],
    ) -> None:
        body = _valid_review_body()
        body["reviewer_notes"] = ""  # violates min_length=1

        resp = client.post(
            "/triage/VQ-2026-0099/review",
            headers=reviewer_headers,
            json=body,
        )
        assert resp.status_code == 422
