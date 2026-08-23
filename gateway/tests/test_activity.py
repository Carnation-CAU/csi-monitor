import unittest
from threading import Event
import numpy as np
from csi_gateway.activity import (
    ActivityFrame,
    ActivityPrediction,
    ActivityPredictionDisplaySmoother,
    AsyncFrameWindowEngine,
    FrameWindowEngine,
    MotionInferenceGate,
)
from csi_gateway.csi import parse_csi_line

class FakeModel:
    def __init__(self): self.calls=0
    def predict(self,window):
        self.calls+=1
        return ActivityPrediction("walking",{"walking":.8,"other_motion":.2},.8,window.first_sequence,
            window.last_sequence,window.finished_at,"fake-v1","test-v1")

class ActivityTest(unittest.TestCase):
    def test_recent_frame_window_and_rate_limit(self):
        model=FakeModel(); engine=FrameWindowEngine(model,window_frames=3,inference_hz=10)
        self.assertIsNone(engine.push(ActivityFrame(1,"1",np.ones(52)),moving=True,now=0))
        self.assertIsNone(engine.push(ActivityFrame(2,"2",np.ones(52)*2),moving=True,now=.01))
        result=engine.push(ActivityFrame(3,"3",np.ones(52)*3),moving=True,now=.02)
        self.assertEqual((result.first_sequence,result.last_sequence),(1,3))
        self.assertIsNone(engine.push(ActivityFrame(4,"4",np.ones(52)*4),moving=True,now=.05))
        result=engine.push(ActivityFrame(5,"5",np.ones(52)*5),moving=True,now=.13)
        self.assertEqual((result.first_sequence,result.last_sequence),(3,5)); self.assertEqual(model.calls,2)
    def test_timestamp_window_is_resampled_to_fixed_rate(self):
        model=FakeModel(); engine=FrameWindowEngine(model,window_frames=3,inference_hz=10,target_rate_hz=100)
        engine.append(ActivityFrame(1,"1",np.zeros(52),0))
        engine.append(ActivityFrame(2,"2",np.ones(52),10_000))
        engine.append(ActivityFrame(3,"3",np.ones(52)*3,20_000))
        window=engine.snapshot()
        self.assertTrue(window.resampled); self.assertAlmostEqual(window.observed_rate_hz,100.0)
        self.assertEqual(window.amplitude.shape,(3,52))
    def test_async_continuous_mode_does_not_require_radar_moving(self):
        model=FakeModel(); engine=AsyncFrameWindowEngine(model,window_frames=1,inference_hz=10)
        try:
            engine.submit(ActivityFrame(1,"1",np.ones(52),0),moving=False,now=0)
            future=engine._future; self.assertIsNotNone(future); future.result(timeout=1)
            self.assertIsNotNone(engine.poll()); self.assertEqual(model.calls,1)
        finally: engine.close()
    def test_csi_parser(self):
        fields=["CSI_DATA","7","2026-01-01T00:00:00Z","0","x","1a:00:00:00:00:00","-55"]+["0"]*12+["6","0","123456"]+["0"]*7
        fields[8]="1"; fields[9]="0"; fields[10]="0"; fields[17]="-98"; fields[27]="104"
        fields.append('"['+','.join(str(i%9-4) for i in range(104))+']"')
        sample=parse_csi_line(','.join(fields))
        self.assertIsNotNone(sample); self.assertEqual(sample.sequence,7); self.assertEqual(sample.amplitude.shape,(52,))
        self.assertEqual(sample.source_mac,"1a:00:00:00:00:00")
        self.assertEqual(sample.channel,6); self.assertEqual(sample.bandwidth,"HT20")
        self.assertEqual(sample.cwb,0); self.assertEqual(sample.secondary_channel,0)
        self.assertEqual(sample.sig_mode,1)
        self.assertEqual(sample.iq.shape,(52,2)); self.assertEqual(sample.rate,0)
        self.assertEqual(int(sample.valid_subcarrier_mask.sum()),48)
    def test_csi_parser_reports_actual_ht40(self):
        fields=["CSI_DATA","8","2026-01-01T00:00:01Z","0","x","mac","-60"]+["0"]*12+["11","1","123466"]+["0"]*7
        fields[8]="1"; fields[9]="0"; fields[10]="1"; fields[17]="-95"; fields[27]="104"
        fields.append('"['+','.join("1" for _ in range(104))+']"')
        sample=parse_csi_line(','.join(fields))
        self.assertIsNotNone(sample)
        self.assertEqual(sample.channel,11); self.assertEqual(sample.bandwidth,"HT40")
        self.assertEqual(sample.cwb,1); self.assertEqual(sample.secondary_channel,1)
    def test_motion_gate_keeps_tail_then_stops(self):
        gate=MotionInferenceGate(tail_seconds=2.0)
        self.assertTrue(gate.update(moving=True,now=1.0))
        self.assertTrue(gate.update(moving=False,now=2.9))
        self.assertFalse(gate.update(moving=False,now=3.1))
        gate.update(moving=True,now=4.0)
        gate.reset()
        self.assertFalse(gate.update(moving=False,now=4.1))
    def test_deactivate_can_discard_calibration_frames(self):
        model=FakeModel(); engine=FrameWindowEngine(model,window_frames=2,inference_hz=10)
        engine.append(ActivityFrame(1,"1",np.ones(52)))
        self.assertEqual(engine.buffered_frames,1)
        engine.clear()
        self.assertEqual(engine.buffered_frames,0)
    def test_async_deactivate_discards_in_flight_prediction(self):
        started=Event(); release=Event()
        class BlockingModel(FakeModel):
            def predict(self,window):
                started.set(); release.wait(1); return super().predict(window)
        model=BlockingModel(); engine=AsyncFrameWindowEngine(model,window_frames=1,inference_hz=10)
        try:
            engine.submit(ActivityFrame(1,"1",np.ones(52)),moving=True,now=0)
            self.assertTrue(started.wait(1))
            future=engine._future
            self.assertIsNotNone(future)
            engine.deactivate(clear_frames=True); release.set(); future.result(timeout=1)
            self.assertIsNone(engine.poll())
            self.assertEqual(engine.window.buffered_frames,0)
        finally:
            release.set(); engine.close()
    def test_prediction_display_is_smoothed_rate_limited_and_held_by_caller(self):
        display=ActivityPredictionDisplaySmoother(history_size=3,refresh_seconds=1.0)
        walking=ActivityPrediction("walking",{"fall_suspected":.1,"walking":.8,"other_motion":.1},.8,1,950,"1","m","p")
        other=ActivityPrediction("other_motion",{"fall_suspected":.1,"walking":.3,"other_motion":.6},.6,2,951,"2","m","p")
        first=display.observe(walking,now=0.0)
        self.assertEqual(first[0],"walking")
        self.assertTrue(display.is_fresh(now=4.9,hold_seconds=5.0))
        self.assertFalse(display.is_fresh(now=5.1,hold_seconds=5.0))
        self.assertIsNone(display.observe(other,now=.2))
        averaged=display.observe(other,now=1.0)
        self.assertEqual(averaged[0],"walking")
        self.assertAlmostEqual(averaged[1]["walking"],(0.8+0.3+0.3)/3)
    def test_first_fall_display_bypasses_refresh_delay(self):
        display=ActivityPredictionDisplaySmoother(refresh_seconds=10.0)
        walking=ActivityPrediction("walking",{"fall_suspected":.1,"walking":.8,"other_motion":.1},.8,1,950,"1","m","p")
        fall=ActivityPrediction("fall_suspected",{"fall_suspected":.95,"walking":.03,"other_motion":.02},.95,2,951,"2","m","p")
        display.observe(walking,now=0.0)
        urgent=display.observe(fall,now=.2)
        self.assertIsNotNone(urgent)
        self.assertEqual(urgent[0],"fall_suspected")
if __name__=="__main__": unittest.main()
