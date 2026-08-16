import unittest
from threading import Event
import numpy as np
from csi_gateway.activity import (
    ActivityFrame,
    ActivityPrediction,
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
    def test_csi_parser(self):
        fields=["CSI_DATA","7","2026-01-01T00:00:00Z","0","x","mac","-55"]+["0"]*12+["6","0","123456"]+["0"]*7
        fields.append('"['+','.join(str(i%9-4) for i in range(104))+']"')
        sample=parse_csi_line(','.join(fields))
        self.assertIsNotNone(sample); self.assertEqual(sample.sequence,7); self.assertEqual(sample.amplitude.shape,(52,))
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
if __name__=="__main__": unittest.main()
