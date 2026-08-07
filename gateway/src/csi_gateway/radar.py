from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class RadarSample:
    sequence: int
    timestamp: str
    wander: float
    someone_threshold: float
    someone: bool
    jitter: float
    move_threshold: float
    moving: bool


@dataclass(frozen=True)
class LinkSample:
    rssi: int
    frequency_hz: int


@dataclass(frozen=True)
class ChannelSample:
    channel: int


@dataclass(frozen=True)
class CalibrationSample:
    someone_threshold: float
    move_threshold: float


@dataclass(frozen=True)
class DeviceMacSample:
    mac: str


def parse_radar_line(line: bytes | str) -> RadarSample | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")

    marker = "RADAR_DADA,"
    marker_index = line.find(marker)
    if marker_index < 0:
        return None

    fields = line[marker_index:].strip().split(",")
    if len(fields) != 11:
        return None

    try:
        return RadarSample(
            sequence=int(fields[1]),
            timestamp=fields[2],
            wander=float(fields[3]),
            someone_threshold=float(fields[5]),
            someone=bool(int(fields[6])),
            jitter=float(fields[7]),
            move_threshold=float(fields[9]),
            moving=bool(int(fields[10])),
        )
    except ValueError:
        return None


def parse_link_line(line: bytes | str) -> LinkSample | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")

    match = re.search(
        r"esp_radar:.*?\brssi:\s*(-?\d+).*?\bfreq:\s*(\d+)Hz",
        line,
    )
    if match is None:
        return None

    return LinkSample(rssi=int(match.group(1)), frequency_hz=int(match.group(2)))


def parse_channel_line(line: bytes | str) -> ChannelSample | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")

    match = re.search(r"(?:^|\s)RF_CHANNEL,(1|6|11)(?:\s|$)", line.strip())
    if match is None:
        return None
    return ChannelSample(channel=int(match.group(1)))


def parse_device_mac_line(line: bytes | str) -> DeviceMacSample | None:
    """연결된 보드 자신의 MAC을 부팅 로그에서 읽는다.

    RX 펌웨어는 시작할 때 `wifi:mode : sta (aa:bb:cc:dd:ee:02)` 형태로
    자기 MAC을 한 번 출력한다. 이미 실행 중인 보드에 붙으면 이 줄이
    나오지 않으므로 관측되지 않을 수 있다.

    `CSI_DATA`의 MAC 필드는 ESP-NOW 브로드캐스트 송신 주소
    (`1a:00:00:00:00:00`)이며 실제 TX 보드 MAC이 아니므로 사용하지 않는다.
    """
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")

    match = re.search(
        r"wifi:mode\s*:\s*sta\s*\(((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})\)",
        line,
    )
    if match is None:
        return None

    mac = match.group(1).lower()
    if mac in {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}:
        return None
    return DeviceMacSample(mac=mac)


def parse_calibration_line(line: bytes | str) -> CalibrationSample | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")

    marker = "RADAR_DADA,"
    marker_index = line.find(marker)
    if marker_index < 0:
        return None
    fields = line[marker_index:].strip().split(",")
    if len(fields) != 9:
        return None
    try:
        return CalibrationSample(
            someone_threshold=float(fields[4]),
            move_threshold=float(fields[7]),
        )
    except ValueError:
        return None
