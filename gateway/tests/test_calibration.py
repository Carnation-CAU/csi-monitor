import unittest

from csi_gateway.calibration import render_channel_results, select_best_channel


class ChannelCalibrationTests(unittest.TestCase):
    def test_selects_stable_channel_before_higher_rssi(self):
        results = {
            1: {
                "samples": 20.0,
                "min_hz": 30.0,
                "avg_hz": 50.0,
                "avg_rssi": -75.0,
                "max_gap": 2.0,
            },
            6: {
                "samples": 20.0,
                "min_hz": 80.0,
                "avg_hz": 90.0,
                "avg_rssi": -50.0,
                "max_gap": 11.0,
            },
        }

        self.assertEqual(select_best_channel(results), 1)

    def test_rejects_channels_without_enough_link_samples(self):
        results = {
            1: {
                "samples": 4.0,
                "min_hz": 50.0,
                "avg_hz": 50.0,
                "avg_rssi": -60.0,
                "max_gap": 1.0,
            }
        }

        self.assertIsNone(select_best_channel(results))

    def test_renders_channel_summary(self):
        rows = render_channel_results(
            [1],
            {
                1: {
                    "samples": 20.0,
                    "min_hz": 48.0,
                    "avg_hz": 62.25,
                    "avg_rssi": -67.5,
                    "max_gap": 1.25,
                }
            },
        )

        self.assertEqual(
            rows,
            ["CH 1: avg 62.2 Hz, min 48 Hz, RSSI -67.5 dBm, max gap 1.2s"],
        )


if __name__ == "__main__":
    unittest.main()
