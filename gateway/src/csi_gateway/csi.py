"""Parse ESP32 CSI_DATA lines into model-ready amplitude frames."""
from __future__ import annotations
import csv,json
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class CsiFrameSample:
    sequence: int
    timestamp: str
    local_timestamp_us: int
    rssi: int
    channel: int
    amplitude: np.ndarray

def parse_csi_line(line: bytes|str) -> CsiFrameSample|None:
    if isinstance(line,bytes): line=line.decode("utf-8",errors="replace")
    marker=line.find("CSI_DATA,")
    if marker<0: return None
    try:
        fields=next(csv.reader([line[marker:].strip()]))
        if len(fields)<30 or fields[0]!="CSI_DATA": return None
        iq=np.asarray(json.loads(fields[29]),dtype=np.float32)
        if iq.shape!=(104,): return None
        pairs=iq.reshape(52,2)
        return CsiFrameSample(int(fields[1]),fields[2],int(fields[21]),int(fields[6]),int(fields[19]),np.hypot(pairs[:,0],pairs[:,1]).astype(np.float32))
    except (ValueError,TypeError,json.JSONDecodeError,csv.Error): return None

