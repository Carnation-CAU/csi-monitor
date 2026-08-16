"""Download and validate the public v5.1 datasets that are excluded from Git."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "dataset" / "raw"

UT_HAR_FILE_ID = "1fEiI3nAoOsddR5qcJQXqz4ocM3aMAcwz"
UT_HAR_ZIP_SIZE = 383_128_602

CSI_HAR_ARTICLE_ID = 14_386_892
CSI_HAR_ZIP_SIZE = 512_739_259
CSI_HAR_ZIP_MD5 = "711e794baee5a0bdab738cc85dcd2a2f"


def _size(path: Path) -> str:
    return f"{path.stat().st_size / 1024**2:.1f} MiB"


def _safe_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()
    print(f"Extracting {archive.name} -> {target}")
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            member_path = (target / member.filename).resolve()
            if os.path.commonpath((target_resolved, member_path)) != str(target_resolved):
                raise RuntimeError(f"Unsafe ZIP member: {member.filename}")
        zf.extractall(target)


def _validate_ut_har(*, quiet: bool = False) -> bool:
    root = RAW / "UT-HAR" / "UT_HAR"
    expected = {
        "data/X_train.csv": (3977, 250, 90),
        "data/X_val.csv": (496, 250, 90),
        "data/X_test.csv": (500, 250, 90),
        "label/y_train.csv": (3977,),
        "label/y_val.csv": (496,),
        "label/y_test.csv": (500,),
    }
    if not all((root / relative).is_file() for relative in expected):
        return False

    import numpy as np

    for relative, shape in expected.items():
        try:
            actual = np.load(root / relative, mmap_mode="r", allow_pickle=False).shape
        except Exception as exc:
            if not quiet:
                print(f"UT-HAR validation failed for {relative}: {exc}")
            return False
        if actual != shape:
            if not quiet:
                print(f"UT-HAR shape mismatch: {relative}: {actual}, expected {shape}")
            return False
    if not quiet:
        print("PASS: UT-HAR (4,973 samples, six processed split files)")
    return True


def _validate_csi_har(*, quiet: bool = False) -> bool:
    root = RAW / "CSI-HAR-3room"
    sessions = sorted(root.glob("room_*/*/data.csv"))
    if len(sessions) != 10:
        if not quiet and root.exists():
            print(f"CSI-HAR validation failed: found {len(sessions)} sessions, expected 10")
        return False
    missing_labels = [data.parent for data in sessions if not (data.parent / "label.csv").is_file()]
    if missing_labels:
        if not quiet:
            print(f"CSI-HAR validation failed: {len(missing_labels)} session(s) lack label.csv")
        return False
    rooms = {data.parents[1].name for data in sessions}
    if rooms != {"room_1", "room_2", "room_3"}:
        if not quiet:
            print(f"CSI-HAR validation failed: rooms are {sorted(rooms)}")
        return False
    if not quiet:
        print("PASS: CSI-HAR-3room (3 rooms, 10 sessions)")
    return True


def _download_ut_har(*, keep_archive: bool) -> None:
    if _validate_ut_har(quiet=True):
        print("SKIP: UT-HAR is already complete.")
        return

    target = RAW / "UT-HAR"
    archive = target / "UT_HAR.zip"
    partial = archive.with_suffix(".zip.part")
    target.mkdir(parents=True, exist_ok=True)

    try:
        import gdown
    except ImportError as exc:
        raise RuntimeError("gdown is missing. Run setup-lab.bat first.") from exc

    if archive.is_file() and archive.stat().st_size != UT_HAR_ZIP_SIZE:
        archive.replace(partial)
    if not archive.is_file():
        print("Downloading UT-HAR processed data from the official SenseFi Google Drive...")
        result = gdown.download(
            id=UT_HAR_FILE_ID,
            output=str(partial),
            quiet=False,
            resume=True,
        )
        if not result or not partial.is_file():
            raise RuntimeError("UT-HAR download did not produce an archive")
        partial.replace(archive)
    if archive.stat().st_size != UT_HAR_ZIP_SIZE:
        raise RuntimeError(
            f"UT-HAR ZIP size mismatch: {archive.stat().st_size:,}, expected {UT_HAR_ZIP_SIZE:,}"
        )
    print(f"UT-HAR archive verified: {_size(archive)}")
    _safe_extract(archive, target)
    if not _validate_ut_har():
        raise RuntimeError("UT-HAR extraction completed, but validation failed")
    if not keep_archive:
        archive.unlink()


def _figshare_download_url() -> str:
    api = f"https://api.figshare.com/v2/articles/{CSI_HAR_ARTICLE_ID}/files"
    print("Reading CSI-HAR file metadata from the official Figshare API...")
    request = urllib.request.Request(api, headers={"User-Agent": "carnation-v5.1-dataset-setup/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        files = json.load(response)
    matches = [
        item
        for item in files
        if item.get("size") == CSI_HAR_ZIP_SIZE
        or str(item.get("computed_md5", item.get("md5", ""))).lower() == CSI_HAR_ZIP_MD5
    ]
    if len(matches) != 1 or not matches[0].get("download_url"):
        raise RuntimeError("Could not identify the CSI-HAR ZIP in the Figshare article")
    return str(matches[0]["download_url"])


def _stream_download(url: str, archive: Path, expected_size: int) -> None:
    partial = archive.with_suffix(archive.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "carnation-v5.1-dataset-setup/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
        print(f"Resuming {archive.name} at {offset / 1024**2:.1f} MiB...")
    else:
        print(f"Downloading {archive.name}...")

    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and offset == expected_size:
            partial.replace(archive)
            return
        raise

    append = offset > 0 and getattr(response, "status", None) == 206
    if offset and not append:
        offset = 0
    mode = "ab" if append else "wb"
    downloaded = offset
    next_report = downloaded + 64 * 1024**2
    with response, partial.open(mode) as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            if downloaded >= next_report:
                print(f"  {downloaded / 1024**2:.0f} / {expected_size / 1024**2:.0f} MiB")
                next_report = downloaded + 64 * 1024**2
    partial.replace(archive)


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_csi_har(*, keep_archive: bool) -> None:
    if _validate_csi_har(quiet=True):
        print("SKIP: CSI-HAR-3room is already complete.")
        return

    target = RAW / "CSI-HAR-3room"
    archive = target / "wifi_csi_har_dataset.zip"
    target.mkdir(parents=True, exist_ok=True)
    if not archive.is_file() or archive.stat().st_size != CSI_HAR_ZIP_SIZE:
        url = _figshare_download_url()
        _stream_download(url, archive, CSI_HAR_ZIP_SIZE)
    if archive.stat().st_size != CSI_HAR_ZIP_SIZE:
        raise RuntimeError(
            f"CSI-HAR ZIP size mismatch: {archive.stat().st_size:,}, expected {CSI_HAR_ZIP_SIZE:,}"
        )
    actual_md5 = _md5(archive)
    if actual_md5 != CSI_HAR_ZIP_MD5:
        raise RuntimeError(f"CSI-HAR ZIP MD5 mismatch: {actual_md5}, expected {CSI_HAR_ZIP_MD5}")
    print(f"CSI-HAR archive verified: {_size(archive)}, MD5 {actual_md5}")
    _safe_extract(archive, target)
    if not _validate_csi_har():
        raise RuntimeError("CSI-HAR extraction completed, but validation failed")
    if not keep_archive:
        archive.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=("ut_har", "csi_har"),
        default=("ut_har", "csi_har"),
    )
    parser.add_argument("--keep-archives", action="store_true")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    print(f"Dataset directory: {RAW}")
    try:
        if "ut_har" in args.datasets:
            _download_ut_har(keep_archive=args.keep_archives)
        if "csi_har" in args.datasets:
            _download_csi_har(keep_archive=args.keep_archives)
    except (OSError, RuntimeError, zipfile.BadZipFile, urllib.error.URLError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    print("PASS: requested public datasets are ready.")


if __name__ == "__main__":
    main()
