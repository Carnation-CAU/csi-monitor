import gc,tempfile,unittest
from pathlib import Path
import numpy as np
from public_datasets import load_ut_har,normalize_per_sample,resize_csi,target_label
class PublicDatasetTest(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual([target_label(x) for x in ["fall","walking","sit_down"]],[0,1,2]); self.assertIsNone(target_label("no_person"))
    def test_resize_normalize(self):
        z=normalize_per_sample(resize_csi(np.arange(20,dtype=np.float32).reshape(4,5),8,3))
        self.assertEqual(z.shape,(8,3)); np.testing.assert_allclose(z.mean(0),0,atol=1e-5)
    def test_ut_binary_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"data").mkdir(); (root/"label").mkdir()
            with (root/"data"/"X_train.csv").open("wb") as f: np.save(f,np.zeros((3,250,90)))
            with (root/"label"/"y_train.csv").open("wb") as f: np.save(f,np.array([1,2,4]))
            x,y,source=load_ut_har(root,"train")
            self.assertEqual(x.shape,(3,250,90)); np.testing.assert_array_equal(y,[0,1,2]); np.testing.assert_array_equal(source,[1,2,4])
            # Close Windows-backed memmaps before TemporaryDirectory removes them.
            del x,y,source
            gc.collect()
if __name__=="__main__": unittest.main()
