"""Parse ESP-CSI CSV rows without discarding training-time information.

ESP-IDF stores each complex value as ``imaginary, real``. The live legacy
model still consumes amplitude, but raw IQ, phase and radio metadata remain
available for S3-native preprocessing and dataset export.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass

import numpy as np

RAW_CSI_ENABLE_COMMAND = (
    "radar --csi_output_type LLFT --csi_output_format decimal"
)

# LLTF legacy-OFDM HT20: DC is absent and the four pilot carriers remain.
LLTF_HT20_SUBCARRIERS = np.asarray(
    [*range(-26, 0), *range(1, 27)], dtype=np.int16
)
LLTF_PILOT_SUBCARRIERS = frozenset({-21, -7, 7, 21})


@dataclass(frozen=True)
class CsiFrameSample:
    sequence: int
    timestamp: str
    local_timestamp_us: int
    source_mac: str
    rssi: int
    rate: int
    sig_mode: int
    mcs: int
    cwb: int
    smoothing: bool
    not_sounding: bool
    aggregation: bool
    stbc: bool
    fec_coding: bool
    sgi: bool
    noise_floor: int
    ampdu_count: int
    channel: int
    secondary_channel: int
    bandwidth: str
    antenna: int
    sig_len: int
    rx_state: int
    agc_gain: int
    fft_gain: int
    csi_length: int
    first_word_invalid: bool
    iq: np.ndarray
    amplitude: np.ndarray
    phase: np.ndarray
    subcarrier_indices: np.ndarray
    valid_subcarrier_mask: np.ndarray
    ltf: str = "LLTF"

    def training_record(self) -> dict[str, object]:
        """Return a JSON-safe lossless CSI representation for new sessions."""
        return {
            "sequence": self.sequence,
            "deviceTimestampUs": self.local_timestamp_us,
            "sourceMac": self.source_mac,
            "channel": self.channel,
            "secondaryChannel": self.secondary_channel,
            "bandwidth": self.bandwidth,
            "ltf": self.ltf,
            "rssi": self.rssi,
            "noiseFloor": self.noise_floor,
            "rate": self.rate,
            "sigMode": self.sig_mode,
            "mcs": self.mcs,
            "cwb": self.cwb,
            "smoothing": self.smoothing,
            "notSounding": self.not_sounding,
            "aggregation": self.aggregation,
            "stbc": self.stbc,
            "fecCoding": self.fec_coding,
            "sgi": self.sgi,
            "ampduCount": self.ampdu_count,
            "antenna": self.antenna,
            "sigLen": self.sig_len,
            "rxState": self.rx_state,
            "agcGain": self.agc_gain,
            "fftGain": self.fft_gain,
            "csiLength": self.csi_length,
            "firstWordInvalid": self.first_word_invalid,
            "iqOrder": ["imag", "real"],
            "iq": self.iq.astype(np.int16, copy=False).tolist(),
            # Derived convenience fields are stored for inspection; IQ remains
            # the source of truth and training recomputes them when needed.
            "amplitude": self.amplitude.tolist(),
            "phase": self.phase.tolist(),
            "subcarrierIndex": self.subcarrier_indices.tolist(),
            "validSubcarrierMask": self.valid_subcarrier_mask.tolist(),
        }


def _subcarrier_layout(complex_count: int) -> tuple[np.ndarray, np.ndarray]:
    if complex_count == len(LLTF_HT20_SUBCARRIERS):
        indices = LLTF_HT20_SUBCARRIERS.copy()
        mask = np.asarray(
            [index not in LLTF_PILOT_SUBCARRIERS for index in indices],
            dtype=bool,
        )
        return indices, mask
    # Preserve unknown/other-LTF layouts instead of inventing RF indices.
    return np.arange(complex_count, dtype=np.int16), np.ones(complex_count, dtype=bool)


def parse_csi_line(line: bytes | str) -> CsiFrameSample | None:
    """Parse one live ESP-CSI CSV row, including raw IQ and RF metadata."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    marker = line.find("CSI_DATA,")
    if marker < 0:
        return None
    try:
        fields = next(csv.reader([line[marker:].strip()]))
        if len(fields) < 30 or fields[0] != "CSI_DATA":
            return None
        flat_iq = np.asarray(json.loads(fields[29]), dtype=np.int16)
        declared_length = int(fields[27])
        if (
            flat_iq.ndim != 1
            or not len(flat_iq)
            or len(flat_iq) % 2
            or declared_length != len(flat_iq)
        ):
            return None
        # ESP-IDF order is imaginary, then real. Keep that exact order in iq.
        iq = flat_iq.reshape(-1, 2)
        imag = iq[:, 0].astype(np.float32)
        real = iq[:, 1].astype(np.float32)
        amplitude = np.hypot(real, imag).astype(np.float32)
        phase = np.arctan2(imag, real).astype(np.float32)
        indices, valid_mask = _subcarrier_layout(len(iq))
        first_word_invalid = bool(int(fields[28]))
        if first_word_invalid:
            valid_mask[: min(2, len(valid_mask))] = False
        # cwb is field 10. Field 9 is MCS; confusing these silently labels
        # non-zero MCS HT20 packets as HT40.
        cwb = int(fields[10])
        return CsiFrameSample(
            sequence=int(fields[1]),
            timestamp=fields[2],
            local_timestamp_us=int(fields[21]),
            source_mac=fields[5],
            rssi=int(fields[6]),
            rate=int(fields[7]),
            sig_mode=int(fields[8]),
            mcs=int(fields[9]),
            cwb=cwb,
            smoothing=bool(int(fields[11])),
            not_sounding=bool(int(fields[12])),
            aggregation=bool(int(fields[13])),
            stbc=bool(int(fields[14])),
            fec_coding=bool(int(fields[15])),
            sgi=bool(int(fields[16])),
            noise_floor=int(fields[17]),
            ampdu_count=int(fields[18]),
            channel=int(fields[19]),
            secondary_channel=int(fields[20]),
            bandwidth="HT40" if cwb else "HT20",
            antenna=int(fields[22]),
            sig_len=int(fields[23]),
            rx_state=int(fields[24]),
            agc_gain=int(fields[25]),
            fft_gain=int(fields[26]),
            csi_length=declared_length,
            first_word_invalid=first_word_invalid,
            iq=iq,
            amplitude=amplitude,
            phase=phase,
            subcarrier_indices=indices,
            valid_subcarrier_mask=valid_mask,
        )
    except (ValueError, TypeError, json.JSONDecodeError, csv.Error, IndexError):
        return None
