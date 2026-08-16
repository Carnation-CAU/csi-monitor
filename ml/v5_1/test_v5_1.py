import sys,unittest
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path: sys.path.insert(0,str(PROJECT))
from collections import Counter
from ml.v5.data_sources import load_spec
from ml.v5.models import make_model
import torch

class V51Test(unittest.TestCase):
    def test_all_dataset_folds_are_disjoint_and_have_all_classes(self):
        for dataset in ("espfi","ut_har","csi_har"):
            spec=load_spec(dataset)
            self.assertEqual(len(spec.folds),4)
            for fold in spec.folds:
                parts=[{s.sample_id for s in rows} for rows in (fold.train,fold.val,fold.test)]
                self.assertFalse(parts[0]&parts[1]); self.assertFalse(parts[0]&parts[2]); self.assertFalse(parts[1]&parts[2])
                for rows in (fold.train,fold.val,fold.test): self.assertEqual(set(Counter(s.label for s in rows)),set(range(len(spec.label_names))))
    def test_all_models_accept_all_public_shapes(self):
        for shape in ((950,52),(250,90),(250,114)):
            x=torch.zeros(2,1,*shape)
            for name in ("simple_cnn","resnet18","efficientnet_b0"):
                with self.subTest(shape=shape,model=name): self.assertEqual(make_model(name,3)(x).shape,(2,3))
if __name__=="__main__": unittest.main()
