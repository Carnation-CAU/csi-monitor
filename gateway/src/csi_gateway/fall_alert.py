from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


EVENT_PATH = "/api/v1/events"


class FallAlertError(RuntimeError):
    """앱 서버에 낙상 의심 이벤트를 전송하지 못했을 때 발생한다."""


def normalize_event_endpoint(value: str) -> str:
    """서버 기본 주소 또는 이벤트 주소를 완전한 이벤트 주소로 바꾼다."""
    endpoint = value.strip()
    if not endpoint:
        raise ValueError("앱 서버 주소가 비어 있습니다.")

    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("앱 서버 주소는 http:// 또는 https:// 로 시작해야 합니다.")
    if parsed.query or parsed.fragment:
        raise ValueError("앱 서버 주소에는 query 또는 fragment를 넣을 수 없습니다.")

    path = parsed.path.rstrip("/")
    if path in {"", "/health"}:
        path = EVENT_PATH
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _require_timezone(timestamp: str) -> None:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("detected_at은 ISO-8601 형식이어야 합니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("detected_at에는 타임존이 필요합니다.")


def build_collection_fall_event(
    *,
    session_id: str,
    detected_at: str,
    room_id: str,
) -> dict[str, Any]:
    """사용자가 확인한 모의 낙상 수집을 앱 계약 v1.0 이벤트로 만든다.

    이 함수의 점수는 모델 확률이 아니다. 현재 수집 테스트 브리지에서는 사용자가
    실제 라벨과 유효성을 확인했다는 사실을 1.0으로 표현한다.
    """
    if not session_id.strip():
        raise ValueError("session_id가 비어 있습니다.")
    if not room_id.strip():
        raise ValueError("room_id가 비어 있습니다.")
    _require_timezone(detected_at)

    return {
        "schema_version": "1.0",
        "event_type": "fall_suspected",
        "window_id": session_id,
        "detected_at": detected_at,
        "room_id": room_id,
        "risk_score": 1.0,
        "evidence": {
            "motion_label": "fall_like",
            "motion_confidence": 1.0,
            "presence_state": "unknown",
            "presence_probability": 0.0,
            "no_recovery_sec": None,
        },
    }


def send_fall_event(
    endpoint: str,
    event: dict[str, Any],
    *,
    timeout: float = 5.0,
) -> None:
    """앱 서버에 이벤트를 보내고 201이 아니면 자세한 오류를 반환한다."""
    url = normalize_event_endpoint(endpoint)
    request = Request(
        url,
        data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body).get("message", body)
        except json.JSONDecodeError:
            message = body
        raise FallAlertError(f"앱 서버가 이벤트를 거부했습니다 ({exc.code}): {message}") from exc
    except URLError as exc:
        raise FallAlertError(f"앱 서버에 연결할 수 없습니다: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FallAlertError("앱 서버 응답 시간이 초과했습니다.") from exc

    if status != 201:
        raise FallAlertError(f"앱 서버가 예상하지 않은 상태 {status}를 반환했습니다: {body}")
