from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from .collection import COLLECTION_LABELS
from .profiles import load_profile, save_profile, utc_now


DATASET_SCHEMA_VERSION = "1.0.0"
PREPROCESSING_VERSION = "1.0.0"
DATASET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{7,80}$")


class DatasetError(ValueError):
    pass


def dataset_path(project_root: Path, dataset_id: str) -> Path:
    return project_root / "data" / "datasets" / dataset_id


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _project_file(project_root: Path, relative_path: str) -> Path:
    root = project_root.resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DatasetError(f"프로젝트 밖의 파일은 내보낼 수 없습니다: {relative_path}") from exc
    return path


def _validate_member_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise DatasetError(f"안전하지 않은 번들 경로입니다: {name}")


def _read_json_bytes(data: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetError(f"{description} JSON을 읽을 수 없습니다.") from exc
    if not isinstance(value, dict):
        raise DatasetError(f"{description}은 JSON 객체여야 합니다.")
    return value


def _validate_jsonl(data: bytes, session_id: str) -> None:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise DatasetError(f"{session_id} 원본이 UTF-8이 아닙니다.") from exc
    if not lines:
        raise DatasetError(f"{session_id} 원본 데이터가 비어 있습니다.")
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(
                f"{session_id} 원본 {line_number}번째 줄이 JSON이 아닙니다."
            ) from exc
        if not isinstance(record, dict) or "raw" not in record:
            raise DatasetError(
                f"{session_id} 원본 {line_number}번째 줄에 raw 필드가 없습니다."
            )


def export_profile_dataset(
    project_root: Path,
    profile_id: str,
    output_path: Path,
    *,
    display_name: str | None = None,
) -> Path:
    project_root = project_root.resolve()
    profile = load_profile(project_root, profile_id)
    sessions: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}

    for manifest_path in sorted((project_root / "data" / "manifests").glob("*.json")):
        manifest_bytes = manifest_path.read_bytes()
        manifest = _read_json_bytes(manifest_bytes, manifest_path.name)
        if manifest.get("profileId") != profile_id or manifest.get("valid") is False:
            continue
        label = str(manifest.get("label", ""))
        if label not in COLLECTION_LABELS:
            continue
        raw_file = manifest.get("rawFile")
        session_id = str(manifest.get("sessionId", "")).strip()
        if not raw_file or not session_id:
            continue
        raw_path = _project_file(project_root, str(raw_file))
        if not raw_path.is_file():
            continue
        raw_bytes = raw_path.read_bytes()
        _validate_jsonl(raw_bytes, session_id)
        raw_member = f"raw/{raw_path.name}"
        manifest_member = f"manifests/{manifest_path.name}"
        payloads[raw_member] = raw_bytes
        payloads[manifest_member] = manifest_bytes
        sessions.append(
            {
                "sessionId": session_id,
                "label": label,
                "rawPath": raw_member,
                "manifestPath": manifest_member,
                "rawSha256": _sha256(raw_bytes),
                "manifestSha256": _sha256(manifest_bytes),
            }
        )

    if not sessions:
        raise DatasetError("이 프로필에 내보낼 유효한 행동 세션이 없습니다.")

    dataset_id = (
        f"dataset-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    )
    metadata = {
        "schemaVersion": DATASET_SCHEMA_VERSION,
        "datasetId": dataset_id,
        "displayName": (display_name or f"{profile['displayName']} 공유 데이터").strip(),
        "createdAtUtc": utc_now(),
        "sourceType": "team-native-esp-radar",
        "sourceProfileId": profile_id,
        "sourceProfileName": profile["displayName"],
        "format": "esp-radar-jsonl",
        "radio": profile.get("radio", {}),
        "preprocessingVersion": PREPROCESSING_VERSION,
        "labels": sorted({str(session["label"]) for session in sessions}),
        "sessions": sessions,
    }

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "dataset.json",
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        )
        for member_name, data in payloads.items():
            archive.writestr(member_name, data)
    return output_path


def import_dataset_bundle(project_root: Path, bundle_path: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    bundle_bytes = bundle_path.read_bytes()
    try:
        with ZipFile(bundle_path, "r") as archive:
            for name in archive.namelist():
                _validate_member_name(name)
            if "dataset.json" not in archive.namelist():
                raise DatasetError("dataset.json이 없는 번들입니다.")
            metadata = _read_json_bytes(archive.read("dataset.json"), "dataset.json")
            if metadata.get("schemaVersion") != DATASET_SCHEMA_VERSION:
                raise DatasetError("지원하지 않는 데이터셋 스키마 버전입니다.")
            if metadata.get("format") != "esp-radar-jsonl":
                raise DatasetError("현재는 esp-radar-jsonl 번들만 가져올 수 있습니다.")
            dataset_id = str(metadata.get("datasetId", ""))
            if not DATASET_ID_PATTERN.fullmatch(dataset_id):
                raise DatasetError("데이터셋 ID 형식이 올바르지 않습니다.")
            sessions = metadata.get("sessions")
            if not isinstance(sessions, list) or not sessions:
                raise DatasetError("가져올 세션이 없는 번들입니다.")

            target = dataset_path(project_root, dataset_id)
            source_hash = _sha256(bundle_bytes)
            if target.exists():
                existing = load_dataset(project_root, dataset_id)
                if existing.get("importedBundleSha256") == source_hash:
                    return existing
                raise DatasetError(f"같은 ID의 다른 데이터셋이 이미 있습니다: {dataset_id}")

            session_payloads: list[tuple[dict[str, Any], bytes, bytes]] = []
            declared_members: set[str] = set()
            for session in sessions:
                if not isinstance(session, dict):
                    raise DatasetError("세션 메타데이터 형식이 올바르지 않습니다.")
                session_id = str(session.get("sessionId", "")).strip()
                label = str(session.get("label", ""))
                raw_member = str(session.get("rawPath", ""))
                manifest_member = str(session.get("manifestPath", ""))
                if not session_id or label not in COLLECTION_LABELS:
                    raise DatasetError("세션 ID 또는 행동 라벨이 올바르지 않습니다.")
                _validate_member_name(raw_member)
                _validate_member_name(manifest_member)
                if not raw_member.startswith("raw/") or not raw_member.endswith(
                    ".jsonl"
                ):
                    raise DatasetError("원본 파일은 raw/*.jsonl 경로여야 합니다.")
                if not manifest_member.startswith(
                    "manifests/"
                ) or not manifest_member.endswith(".json"):
                    raise DatasetError("manifest 파일 경로가 올바르지 않습니다.")
                if raw_member in declared_members or manifest_member in declared_members:
                    raise DatasetError("번들에 중복 선언된 세션 파일이 있습니다.")
                declared_members.update((raw_member, manifest_member))
                try:
                    raw_bytes = archive.read(raw_member)
                    manifest_bytes = archive.read(manifest_member)
                except KeyError as exc:
                    raise DatasetError(f"번들 세션 파일이 없습니다: {exc}") from exc
                if _sha256(raw_bytes) != session.get("rawSha256"):
                    raise DatasetError(f"{session_id} 원본 체크섬이 일치하지 않습니다.")
                if _sha256(manifest_bytes) != session.get("manifestSha256"):
                    raise DatasetError(f"{session_id} manifest 체크섬이 일치하지 않습니다.")
                _validate_jsonl(raw_bytes, session_id)
                manifest = _read_json_bytes(manifest_bytes, manifest_member)
                if manifest.get("sessionId") != session_id or manifest.get("label") != label:
                    raise DatasetError(f"{session_id} manifest 정보가 번들과 다릅니다.")
                session_payloads.append((session, raw_bytes, manifest_bytes))
    except BadZipFile as exc:
        raise DatasetError("올바른 ZIP 데이터셋 번들이 아닙니다.") from exc

    target.mkdir(parents=True)
    try:
        for session, raw_bytes, manifest_bytes in session_payloads:
            raw_target = target / str(session["rawPath"])
            manifest_target = target / str(session["manifestPath"])
            raw_target.parent.mkdir(parents=True, exist_ok=True)
            manifest_target.parent.mkdir(parents=True, exist_ok=True)
            raw_target.write_bytes(raw_bytes)
            manifest_target.write_bytes(manifest_bytes)
        metadata["importedAtUtc"] = utc_now()
        metadata["importedBundleSha256"] = source_hash
        (target / "dataset.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        for path in sorted(target.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        target.rmdir()
        raise
    return metadata


def load_dataset(project_root: Path, dataset_id: str) -> dict[str, Any]:
    path = dataset_path(project_root, dataset_id) / "dataset.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_datasets(project_root: Path) -> list[dict[str, Any]]:
    root = project_root / "data" / "datasets"
    if not root.exists():
        return []
    datasets = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in root.glob("*/dataset.json")
    ]
    return sorted(datasets, key=lambda item: str(item.get("displayName", "")))


def attach_dataset_to_profile(
    project_root: Path, profile: dict[str, Any], dataset_id: str
) -> Path:
    dataset = load_dataset(project_root, dataset_id)
    references = profile.setdefault("referenceDatasets", [])
    if not any(item.get("datasetId") == dataset_id for item in references):
        references.append(
            {
                "datasetId": dataset_id,
                "role": "reference",
                "preprocessingVersion": dataset.get(
                    "preprocessingVersion", PREPROCESSING_VERSION
                ),
                "attachedAtUtc": utc_now(),
            }
        )
    return save_profile(project_root, profile)


def detach_dataset_from_profile(
    project_root: Path, profile: dict[str, Any], dataset_id: str
) -> Path:
    references = profile.setdefault("referenceDatasets", [])
    profile["referenceDatasets"] = [
        item for item in references if item.get("datasetId") != dataset_id
    ]
    return save_profile(project_root, profile)
