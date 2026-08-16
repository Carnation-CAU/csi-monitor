import unittest
import numpy as np
from csi_gateway.activity import ActivityFrame,ActivityPrediction,FrameWindowEngine
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
if __name__=="__main__": unittest.main()
