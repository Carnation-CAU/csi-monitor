import unittest

from csi_gateway.presence import PresenceDetector, PresenceState
from csi_gateway.radar import RadarSample


def radar_sample(*, someone: bool = False, moving: bool = False) -> RadarSample:
    return RadarSample(
        sequence=1,
        timestamp="0",
        wander=0.1 if someone else 0.0,
        someone_threshold=0.05,
        someone=someone,
        jitter=0.1 if moving else 0.0,
        move_threshold=0.05,
        moving=moving,
    )


class PresenceDetectorTests(unittest.TestCase):
    def make_detector(self, **overrides) -> PresenceDetector:
        settings = {
            "window_seconds": 4.0,
            "min_samples": 3,
            "presence_confirm_seconds": 1.0,
            "absence_confirm_seconds": 3.0,
            "link_timeout_seconds": 5.0,
        }
        settings.update(overrides)
        return PresenceDetector(**settings)

    def test_uncalibrated_profile_is_unknown(self):
        detector = self.make_detector()

        decision = detector.update(
            radar_sample(someone=True), calibrated=False, observed_at=0.0
        )

        self.assertEqual(decision.state, PresenceState.UNKNOWN)
        self.assertEqual(decision.reason, "calibration_required")

    def test_stationary_person_becomes_present_static(self):
        detector = self.make_detector()

        for observed_at in (0.0, 0.5, 1.0):
            decision = detector.update(
                radar_sample(someone=True),
                calibrated=True,
                observed_at=observed_at,
            )
        self.assertEqual(decision.state, PresenceState.UNKNOWN)
        self.assertEqual(decision.reason, "confirming_presence")

        decision = detector.update(
            radar_sample(someone=True), calibrated=True, observed_at=2.0
        )

        self.assertEqual(decision.state, PresenceState.PRESENT_STATIC)
        self.assertEqual(decision.presence_ratio, 1.0)

    def test_movement_immediately_overrides_absent_state(self):
        detector = self.make_detector(
            absence_confirm_seconds=1.0,
            presence_confirm_seconds=10.0,
        )
        for observed_at in (0.0, 0.5, 1.0, 2.0):
            decision = detector.update(
                radar_sample(), calibrated=True, observed_at=observed_at
            )
        self.assertEqual(decision.state, PresenceState.ABSENT)

        decision = detector.update(
            radar_sample(moving=True), calibrated=True, observed_at=2.1
        )

        self.assertEqual(decision.state, PresenceState.PRESENT_ACTIVE)
        self.assertEqual(decision.reason, "movement_detected")

    def test_absence_requires_continuous_confirmation(self):
        detector = self.make_detector(absence_confirm_seconds=3.0)

        for observed_at in (0.0, 1.0, 2.0, 4.0):
            decision = detector.update(
                radar_sample(), calibrated=True, observed_at=observed_at
            )
        self.assertEqual(decision.state, PresenceState.UNKNOWN)
        self.assertEqual(decision.reason, "confirming_absence")

        decision = detector.update(
            radar_sample(), calibrated=True, observed_at=5.0
        )

        self.assertEqual(decision.state, PresenceState.ABSENT)

    def test_previous_presence_is_held_while_absence_is_confirmed(self):
        detector = self.make_detector(
            window_seconds=2.0,
            min_samples=2,
            presence_confirm_seconds=0.0,
            absence_confirm_seconds=2.0,
        )
        detector.update(
            radar_sample(someone=True), calibrated=True, observed_at=0.0
        )
        decision = detector.update(
            radar_sample(someone=True), calibrated=True, observed_at=1.0
        )
        self.assertEqual(decision.state, PresenceState.PRESENT_STATIC)

        for observed_at in (2.0, 3.0, 4.0, 5.0):
            decision = detector.update(
                radar_sample(), calibrated=True, observed_at=observed_at
            )
        self.assertEqual(decision.state, PresenceState.PRESENT_STATIC)
        self.assertEqual(decision.reason, "confirming_absence")

        decision = detector.update(
            radar_sample(), calibrated=True, observed_at=6.0
        )
        self.assertEqual(decision.state, PresenceState.ABSENT)

    def test_radar_timeout_changes_state_to_unknown(self):
        detector = self.make_detector(presence_confirm_seconds=0.0)
        for observed_at in (0.0, 0.5, 1.0):
            decision = detector.update(
                radar_sample(someone=True),
                calibrated=True,
                observed_at=observed_at,
            )
        self.assertEqual(decision.state, PresenceState.PRESENT_STATIC)

        decision = detector.health(calibrated=True, observed_at=6.1)

        self.assertEqual(decision.state, PresenceState.UNKNOWN)
        self.assertEqual(decision.reason, "radar_timeout")


if __name__ == "__main__":
    unittest.main()
