from collections.abc import Mapping
from typing import Any

from app.main import create_app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

EXPECTED_REST_OPERATIONS = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/bootstrap"),
    ("GET", "/api/v1/profiles"),
    ("POST", "/api/v1/profiles"),
    ("GET", "/api/v1/profiles/{profileId}"),
    ("PATCH", "/api/v1/profiles/{profileId}"),
    ("POST", "/api/v1/profiles/{profileId}/behavior-warning-sensitivity/drive-summary"),
    ("DELETE", "/api/v1/profiles/{profileId}"),
    ("POST", "/api/v1/profiles/{profileId}/select"),
    ("GET", "/api/v1/profiles/{profileId}/saved-places"),
    ("PUT", "/api/v1/profiles/{profileId}/saved-places/{placeType}"),
    ("POST", "/api/v1/profiles/{profileId}/favorites"),
    ("PATCH", "/api/v1/saved-places/{placeId}"),
    ("DELETE", "/api/v1/saved-places/{placeId}"),
    ("GET", "/api/v1/profiles/{profileId}/search-histories"),
    ("POST", "/api/v1/profiles/{profileId}/search-histories"),
    ("DELETE", "/api/v1/profiles/{profileId}/search-histories"),
    ("POST", "/api/v1/driving-sessions"),
    ("GET", "/api/v1/driving-sessions/active"),
    ("GET", "/api/v1/driving-sessions/{sessionId}"),
    ("POST", "/api/v1/driving-sessions/{sessionId}/end"),
    ("GET", "/api/v1/profiles/{profileId}/driving-sessions"),
    ("GET", "/api/v1/driving-sessions/{sessionId}/timeline"),
    ("GET", "/api/v1/driving-sessions/{sessionId}/locations"),
    ("POST", "/api/v1/driving-sessions/{sessionId}/agent/conversations"),
    ("GET", "/api/v1/agent/conversations/{conversationId}"),
    ("POST", "/api/v1/agent/behavior-events/{behaviorEventId}/interventions"),
    ("POST", "/api/v1/agent/conversations/{conversationId}/messages"),
    ("POST", "/api/v1/agent/interventions/{interventionId}/responses"),
    ("GET", "/api/v1/profiles/{profileId}/reports/summary"),
    ("GET", "/api/v1/profiles/{profileId}/reports/narrative"),
    ("GET", "/api/v1/profiles/{profileId}/reports/behavior-events"),
    ("GET", "/api/v1/profiles/{profileId}/reports/sessions"),
    ("GET", "/api/v1/music/recommendations"),
    ("POST", "/api/v1/voice/tts"),
    ("POST", "/api/v1/manual-risk/voice/transcriptions"),
    ("POST", "/api/v1/manual-risk/voice/matches"),
}

FORBIDDEN_REST_OPERATIONS = {
    ("POST", "/api/v1/profiles/{profileId}/report-exports"),
    ("GET", "/api/v1/profiles/{profileId}/report-exports"),
    ("GET", "/api/v1/report-exports/{exportId}"),
    ("GET", "/api/v1/report-exports/{exportId}/download"),
    ("POST", "/api/v1/report-exports/{exportId}/email"),
    ("POST", "/api/v1/demo/sessions/{sessionId}/driving-state"),
    ("POST", "/api/v1/demo/sessions/{sessionId}/behavior-events"),
    ("POST", "/api/v1/demo/sessions/{sessionId}/responses"),
    ("POST", "/api/v1/demo/external-errors"),
    ("DELETE", "/api/v1/demo/reset"),
    ("POST", "/api/v1/tool-executions/{toolExecutionId}/confirm"),
    ("POST", "/api/v1/tool-executions/{toolExecutionId}/reject"),
}

EXPECTED_SUCCESS_RESPONSES = {
    ("POST", "/api/v1/profiles"): {"201"},
    ("DELETE", "/api/v1/profiles/{profileId}"): {"204"},
    ("PUT", "/api/v1/profiles/{profileId}/saved-places/{placeType}"): {"200"},
    ("POST", "/api/v1/profiles/{profileId}/favorites"): {"201"},
    ("POST", "/api/v1/profiles/{profileId}/search-histories"): {"201"},
    ("DELETE", "/api/v1/saved-places/{placeId}"): {"204"},
    ("POST", "/api/v1/driving-sessions"): {"201"},
    ("GET", "/api/v1/driving-sessions/active"): {"200", "204"},
    ("POST", "/api/v1/driving-sessions/{sessionId}/end"): {"200"},
    ("POST", "/api/v1/driving-sessions/{sessionId}/agent/conversations"): {"201"},
    ("GET", "/api/v1/agent/conversations/{conversationId}"): {"200"},
    ("POST", "/api/v1/agent/behavior-events/{behaviorEventId}/interventions"): {"201"},
    ("POST", "/api/v1/agent/conversations/{conversationId}/messages"): {"201"},
    ("POST", "/api/v1/agent/interventions/{interventionId}/responses"): {"201"},
    ("GET", "/api/v1/profiles/{profileId}/reports/summary"): {"200"},
    ("GET", "/api/v1/profiles/{profileId}/reports/narrative"): {"200"},
    ("GET", "/api/v1/profiles/{profileId}/reports/behavior-events"): {"200"},
    ("GET", "/api/v1/profiles/{profileId}/reports/sessions"): {"200"},
    ("GET", "/api/v1/music/recommendations"): {"200"},
    ("POST", "/api/v1/voice/tts"): {"200"},
    ("POST", "/api/v1/manual-risk/voice/transcriptions"): {"200"},
    ("POST", "/api/v1/manual-risk/voice/matches"): {"200"},
}


def test_openapi_exposes_only_current_rest_operation_matrix() -> None:
    spec = create_app().openapi()

    actual_operations = {
        (method.upper(), path)
        for path, path_spec in spec["paths"].items()
        for method in path_spec
        if method in HTTP_METHODS
    }

    assert actual_operations == EXPECTED_REST_OPERATIONS
    assert len(actual_operations) == 37
    assert not (actual_operations & FORBIDDEN_REST_OPERATIONS)
    assert all(path.startswith("/api/v1/") for _, path in actual_operations)
    assert all(not path.startswith("/api/v1/api/v1/") for _, path in actual_operations)
    assert "/ws/v1/driving-sessions/{sessionId}" not in spec["paths"]
    assert all("/demo/" not in path for _, path in actual_operations)
    assert all("/report-exports" not in path for _, path in actual_operations)
    assert all("confirm" not in path and "reject" not in path for _, path in actual_operations)


def test_openapi_operation_ids_are_unique() -> None:
    spec = create_app().openapi()

    operation_ids = [
        path_spec[method]["operationId"]
        for path_spec in spec["paths"].values()
        for method in path_spec
        if method in HTTP_METHODS
    ]

    assert len(operation_ids) == len(set(operation_ids))


def test_openapi_documents_success_status_and_no_content_contracts() -> None:
    spec = create_app().openapi()

    for operation_key, expected_statuses in EXPECTED_SUCCESS_RESPONSES.items():
        responses = _operation(spec, operation_key)["responses"]
        assert expected_statuses <= set(responses)

    for operation_key in [
        ("DELETE", "/api/v1/profiles/{profileId}"),
        ("DELETE", "/api/v1/saved-places/{placeId}"),
        ("GET", "/api/v1/driving-sessions/active"),
    ]:
        response_204 = _operation(spec, operation_key)["responses"]["204"]
        assert "content" not in response_204


def test_openapi_documents_core_query_parameter_contracts() -> None:
    spec = create_app().openapi()

    location_limit = _query_schema(
        spec,
        ("GET", "/api/v1/driving-sessions/{sessionId}/locations"),
        "limit",
    )
    assert location_limit["default"] == 1000
    assert location_limit["minimum"] == 1
    assert location_limit["maximum"] == 5000

    for operation_key in [
        ("GET", "/api/v1/profiles/{profileId}/search-histories"),
        ("GET", "/api/v1/profiles/{profileId}/driving-sessions"),
        ("GET", "/api/v1/profiles/{profileId}/reports/sessions"),
    ]:
        page_schema = _query_schema(spec, operation_key, "page")
        size_schema = _query_schema(spec, operation_key, "size")
        assert page_schema["default"] == 1
        assert page_schema["minimum"] == 1
        assert size_schema["default"] == 20
        assert size_schema["minimum"] == 1
        assert size_schema["maximum"] == 100

    for operation_key in [
        ("GET", "/api/v1/profiles/{profileId}/reports/summary"),
        ("GET", "/api/v1/profiles/{profileId}/reports/narrative"),
        ("GET", "/api/v1/profiles/{profileId}/reports/behavior-events"),
        ("GET", "/api/v1/profiles/{profileId}/reports/sessions"),
    ]:
        assert _query_parameter(spec, operation_key, "periodStart")["required"] is True
        assert _query_parameter(spec, operation_key, "periodEnd")["required"] is True


def test_openapi_documents_schema_field_exposure_contracts() -> None:
    spec = create_app().openapi()
    schemas = spec["components"]["schemas"]

    profile_properties = schemas["ProfileResponse"]["properties"]
    assert "accountId" not in profile_properties

    agent_create = schemas["AgentConversationCreateRequest"]
    assert "mode" in agent_create["required"]

    agent_detail = schemas["AgentConversationDetailResponse"]
    assert {
        "id",
        "sessionId",
        "mode",
        "status",
        "startedAt",
        "endedAt",
        "messages",
    } <= set(agent_detail["required"])
    assert set(agent_detail["properties"]) == {
        "id",
        "sessionId",
        "mode",
        "status",
        "startedAt",
        "endedAt",
        "messages",
    }

    agent_message = schemas["AgentMessageResponse"]
    assert {
        "id",
        "sequenceNo",
        "role",
        "text",
        "intent",
        "inputType",
        "createdAt",
    } <= set(agent_message["required"])
    assert set(agent_message["properties"]) == {
        "id",
        "sequenceNo",
        "role",
        "text",
        "intent",
        "inputType",
        "createdAt",
    }
    assert "conversationId" not in agent_message["properties"]
    assert "metadataJson" not in agent_message["properties"]


def _operation(spec: Mapping[str, Any], key: tuple[str, str]) -> Mapping[str, Any]:
    method, path = key
    return spec["paths"][path][method.lower()]


def _query_parameter(
    spec: Mapping[str, Any],
    key: tuple[str, str],
    name: str,
) -> Mapping[str, Any]:
    for parameter in _operation(spec, key).get("parameters", []):
        if parameter["in"] == "query" and parameter["name"] == name:
            return parameter
    raise AssertionError(f"Missing query parameter {name} for {key}")


def _query_schema(
    spec: Mapping[str, Any],
    key: tuple[str, str],
    name: str,
) -> Mapping[str, Any]:
    return _query_parameter(spec, key, name)["schema"]
