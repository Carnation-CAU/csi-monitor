import unittest
from pathlib import Path
import torch
from dataset import index_espfi,split_records
from models import make_model

class V5Test(unittest.TestCase):
    def test_model_shapes(self):
        x=torch.zeros(2,1,950,52)
        for name in ("simple_cnn","resnet18"):
            with self.subTest(name=name): self.assertEqual(tuple(make_model(name)(x).shape),(2,3))
    def test_real_split_if_installed(self):
        root=Path(__file__).resolve().parents[1]/"dataset"/"raw"/"ESP-Fi-HAR-full"
        if not root.exists(): self.skipTest("ESP-Fi not installed")
        splits=split_records(index_espfi(root),"participant")
        self.assertEqual({k:len(v) for k,v in splits.items()},{"train":1400,"val":280,"test":560})
        self.assertEqual({r.participant for r in splits["train"]},{1,2,3,4,5})
        self.assertEqual({r.participant for r in splits["val"]},{6})
        self.assertEqual({r.participant for r in splits["test"]},{7,8})
if __name__=="__main__": unittest.main()

