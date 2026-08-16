from __future__ import annotations


def select_best_channel(
    results: dict[int, dict[str, float]],
    *,
    minimum_link_samples: int = 5,
) -> int | None:
    """링크 연속성, 패킷률, RSSI 순서로 가장 안정적인 채널을 고른다."""
    valid = {
        channel: result
        for channel, result in results.items()
        if result["samples"] >= minimum_link_samples
    }
    if not valid:
        return None
    return max(
        valid,
        key=lambda channel: (
            valid[channel]["max_gap"] < 10,
            valid[channel]["min_hz"],
            valid[channel]["avg_hz"],
            -valid[channel]["max_gap"],
            valid[channel]["avg_rssi"],
        ),
    )


def render_channel_results(
    channels: list[int], results: dict[int, dict[str, float]]
) -> list[str]:
    rows = []
    for channel in channels:
        result = results[channel]
        rows.append(
            f"CH {channel}: avg {result['avg_hz']:.1f} Hz, "
            f"min {result['min_hz']:.0f} Hz, RSSI {result['avg_rssi']:.1f} dBm, "
            f"max gap {result['max_gap']:.1f}s"
        )
    return rows
