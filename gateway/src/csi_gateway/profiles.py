from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROFILE_ID = "default-space"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def profile_path(project_root: Path, profile_id: str) -> Path:
    return project_root / "data" / "profiles" / f"{profile_id}.json"


def load_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    return json.loads(profile_path(project_root, profile_id).read_text(encoding="utf-8"))


def list_profiles(project_root: Path) -> list[dict[str, Any]]:
    load_or_create_profile(project_root)
    profiles_dir = project_root / "data" / "profiles"
    profiles = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in profiles_dir.glob("*.json")
    ]
    return sorted(profiles, key=lambda profile: str(profile["displayName"]))


def create_profile(
    project_root: Path,
    *,
    display_name: str,
    placement_description: str,
    distance_meters: float,
    channel: int,
    tx_mac: str | None = None,
    rx_mac: str | None = None,
) -> dict[str, Any]:
    """새 공간 프로필을 만든다.

    MAC을 넘기지 않으면 `null`로 남긴다. 보드 MAC은 실행 환경마다 다르므로
    기본값을 임의로 채우면 다른 보드를 쓰는 사용자의 프로필에 잘못된 출처가
    기록된다. RX MAC은 부팅 로그가 관측되면 모니터가 자동으로 채운다.
    """
    profile_id = datetime.now().strftime("space-%Y%m%d-%H%M%S-%f")
    now = utc_now()
    profile = {
        "schemaVersion": "1.0.0",
        "profileId": profile_id,
        "displayName": display_name.strip(),
        "roomId": profile_id,
        "createdAtUtc": now,
        "updatedAtUtc": now,
        "placement": {
            "description": placement_description.strip(),
            "txRxDistanceMeters": distance_meters,
            "txPosition": "사용자가 기록한 위치",
            "rxPosition": "사용자가 기록한 위치",
            "antennaGuidance": "보정 당시의 높이와 안테나 방향을 동일하게 복원",
        },
        "radio": {"channel": channel, "bandwidth": "HT40", "txRateHz": 100},
        "calibration": None,
        "needsCalibration": True,
        "devices": {
            "txMac": tx_mac,
            "rxMac": rx_mac,
        },
        "sessionIds": [],
        "notes": ["새 공간 프로필: 빈 공간 보정 필요"],
    }
    save_profile(project_root, profile)
    return profile


def archive_profile(project_root: Path, profile_id: str) -> Path:
    source = profile_path(project_root, profile_id)
    archive_dir = project_root / "data" / "profiles" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_at = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = archive_dir / f"{profile_id}-{archived_at}.json"
    source.replace(target)
    return target


def default_workspace_profile() -> dict[str, Any]:
    """프로필이 하나도 없을 때 만드는 빈 기본 프로필.

    측정 환경은 사용자마다 다르므로 배치·거리·보정값·MAC을 채우지 않는다.
    사용자가 실제 배치를 입력하고 빈 공간 보정을 마치면 그때 값이 채워진다.
    """
    return {
        "schemaVersion": "1.0.0",
        "profileId": DEFAULT_PROFILE_ID,
        "displayName": "기본 공간",
        "roomId": DEFAULT_PROFILE_ID,
        "createdAtUtc": utc_now(),
        "updatedAtUtc": utc_now(),
        "placement": {
            "description": "",
            "txRxDistanceMeters": None,
            "txPosition": "",
            "rxPosition": "",
            "antennaGuidance": "보정 당시의 높이와 안테나 방향을 동일하게 복원",
        },
        "radio": {"channel": 6, "bandwidth": "HT40", "txRateHz": 100},
        "calibration": None,
        "needsCalibration": True,
        "devices": {
            "txMac": None,
            "rxMac": None,
        },
        "sessionIds": [],
        "notes": [
            "기본 프로필: 실제 배치를 기록하고 빈 공간 보정을 실행해야 함",
        ],
    }


def load_or_create_profile(project_root: Path) -> dict[str, Any]:
    path = profile_path(project_root, DEFAULT_PROFILE_ID)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    profile = default_workspace_profile()
    save_profile(project_root, profile)
    return profile


def save_profile(project_root: Path, profile: dict[str, Any]) -> Path:
    path = profile_path(project_root, str(profile["profileId"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    profile["updatedAtUtc"] = utc_now()
    path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def update_profile_channel(
    project_root: Path, profile: dict[str, Any], channel: int
) -> Path:
    profile["radio"]["channel"] = channel
    profile["calibration"] = None
    profile["needsCalibration"] = True
    return save_profile(project_root, profile)


def update_profile_calibration(
    project_root: Path,
    profile: dict[str, Any],
    *,
    someone_threshold: float,
    move_threshold: float,
) -> Path:
    profile["calibration"] = {
        "someoneThreshold": someone_threshold,
        "moveThreshold": move_threshold,
        "someoneSensitivity": 0.15,
        "moveSensitivity": 0.20,
        "bufferSize": 5,
        "outliersNumber": 2,
        "calibratedAtUtc": utc_now(),
    }
    profile["needsCalibration"] = False
    return save_profile(project_root, profile)


def update_profile_rx_mac(
    project_root: Path, profile: dict[str, Any], rx_mac: str
) -> Path | None:
    """관측된 RX MAC을 프로필에 기록한다.

    이미 값이 있으면 덮어쓰지 않는다. 사용자가 직접 적어 둔 값이나 다른 보드의
    기록을 자동 관측이 조용히 바꾸지 않도록 하기 위해서다. 값이 바뀌었다면
    보드를 교체한 것이므로 새 프로필을 만드는 편이 맞다.

    기록할 것이 없으면 `None`을 반환한다.
    """
    devices = profile.setdefault("devices", {})
    if devices.get("rxMac"):
        return None
    devices["rxMac"] = rx_mac
    return save_profile(project_root, profile)


def append_profile_session(
    project_root: Path, profile: dict[str, Any], session_id: str
) -> Path:
    sessions = profile.setdefault("sessionIds", [])
    if session_id not in sessions:
        sessions.append(session_id)
    return save_profile(project_root, profile)
