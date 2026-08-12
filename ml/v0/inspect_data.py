"""Inspect local/project Wi-Fi CSI data without modifying existing project code."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


CSI_ARRAY_RE = re.compile(r'CSI_DATA.*?(\[[^\r\n]*\])')


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def basic_stats(values: list[float]) -> dict[str, float | int | None]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(finite),
        "min": min(finite),
        "max": max(finite),
        "mean": sum(finite) / len(finite),
    }


def parse_csi_array(raw: str) -> list[float] | None:
    match = CSI_ARRAY_RE.search(raw)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or not all(finite_number(value) for value in parsed):
        return None
    return [float(value) for value in parsed]


def parse_radar(raw: str) -> dict[str, float] | None:
    marker = "RADAR_DADA,"
    marker_index = raw.find(marker)
    if marker_index < 0:
        return None
    fields = raw[marker_index:].strip().split(",")
    if len(fields) != 11:
        return None
    try:
        return {
            "wander": float(fields[3]),
            "jitter": float(fields[7]),
            "move_threshold": float(fields[9]),
            "moving": float(fields[10]),
        }
    except ValueError:
        return None


def inspect_jsonl(path: Path) -> dict[str, Any]:
    labels: Counter[str] = Counter()
    records = 0
    invalid_json = 0
    csi_frames = 0
    malformed_csi = 0
    csi_lengths: Counter[int] = Counter()
    csi_values: list[float] = []
    radar_frames = 0
    radar_values: dict[str, list[float]] = {
        "wander": [],
        "jitter": [],
        "move_threshold": [],
        "moving": [],
    }

    with path.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_json += 1
                continue
            if not isinstance(record, dict):
                invalid_json += 1
                continue
            records += 1
            labels[str(record.get("label", "unknown"))] += 1
            raw = str(record.get("raw", ""))

            if "CSI_DATA" in raw:
                csi = parse_csi_array(raw)
                if csi is None:
                    malformed_csi += 1
                else:
                    csi_frames += 1
                    csi_lengths[len(csi)] += 1
                    csi_values.extend(csi)

            radar = parse_radar(raw)
            if radar is not None:
                radar_frames += 1
                for key, value in radar.items():
                    radar_values[key].append(value)

    return {
        "path": str(path),
        "format": "project_jsonl",
        "records": records,
        "invalid_json_lines": invalid_json,
        "labels": dict(labels),
        "csi_frames": csi_frames,
        "malformed_csi_frames": malformed_csi,
        "csi_array_lengths": {str(key): value for key, value in sorted(csi_lengths.items())},
        "csi_value_stats": basic_stats(csi_values),
        "radar_frames": radar_frames,
        "radar_stats": {key: basic_stats(values) for key, values in radar_values.items()},
    }


def inspect_mat(path: Path) -> dict[str, Any]:
    try:
        import numpy as np
        from scipy.io import loadmat
    except ImportError as error:
        return {
            "path": str(path),
            "format": "mat",
            "error": f"NumPy/SciPy is required: {error}",
        }

    try:
        content = loadmat(path)
    except (NotImplementedError, OSError, ValueError) as error:
        return {
            "path": str(path),
            "format": "mat",
            "error": str(error),
            "hint": "MATLAB v7.3 files may require an HDF5 reader.",
        }

    arrays = []
    for key, value in content.items():
        if key.startswith("__") or not isinstance(value, np.ndarray):
            continue
        item: dict[str, Any] = {
            "key": key,
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "complex": bool(np.iscomplexobj(value)),
        }
        if np.issubdtype(value.dtype, np.number) and value.size:
            magnitude = np.abs(value) if np.iscomplexobj(value) else value.astype(float)
            finite = magnitude[np.isfinite(magnitude)]
            if finite.size:
                item["min"] = float(finite.min())
                item["max"] = float(finite.max())
                item["mean"] = float(finite.mean())
        arrays.append(item)

    return {
        "path": str(path),
        "format": "mat",
        "arrays": arrays,
    }


def flatten_file_row(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("format") == "project_jsonl":
        return {
            "path": result["path"],
            "format": result["format"],
            "records": result["records"],
            "csi_frames": result["csi_frames"],
            "radar_frames": result["radar_frames"],
            "shapes": json.dumps(result["csi_array_lengths"], ensure_ascii=False),
            "error": "",
        }
    arrays = result.get("arrays", [])
    shapes = {array["key"]: array["shape"] for array in arrays}
    return {
        "path": result["path"],
        "format": result.get("format", "unknown"),
        "records": "",
        "csi_frames": "",
        "radar_frames": "",
        "shapes": json.dumps(shapes, ensure_ascii=False),
        "error": result.get("error", ""),
    }


def inspect_path(input_path: Path) -> list[dict[str, Any]]:
    if input_path.is_file():
        candidates = [input_path]
    elif input_path.is_dir():
        candidates = sorted(
            path
            for path in input_path.rglob("*")
            if path.is_file() and path.suffix.lower() in {".jsonl", ".mat"}
        )
    else:
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    results = []
    for path in candidates:
        if path.suffix.lower() == ".jsonl":
            results.append(inspect_jsonl(path))
        elif path.suffix.lower() == ".mat":
            results.append(inspect_mat(path))
    return results


def write_report(results: list[dict[str, Any]], input_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "input": str(input_path.resolve()),
        "supported_files": len(results),
        "formats": dict(Counter(result.get("format", "unknown") for result in results)),
        "files": results,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = [
        "path",
        "format",
        "records",
        "csi_frames",
        "radar_frames",
        "shapes",
        "error",
    ]
    with (output_dir / "files.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flatten_file_row(result) for result in results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Wi-Fi CSI dataset files")
    parser.add_argument("--input", default="data/raw", help="A .jsonl/.mat file or directory")
    parser.add_argument("--output", default="ml/v0/output", help="Report directory")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output)
    try:
        results = inspect_path(input_path)
    except FileNotFoundError as error:
        print(error)
        return 2

    write_report(results, input_path, output_dir)
    if not results:
        print(f"No supported .jsonl or .mat files found under {input_path}.")
    else:
        print(f"Inspected {len(results)} file(s).")
    print(f"Report: {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

