from collections import Counter
from pathlib import Path
from public_datasets import TARGET_NAMES,iter_csi_har_windows,load_ut_har
HERE=Path(__file__).resolve().parent
RAW=HERE/"raw"
def main():
    print("UT-HAR")
    for split in ("train","val","test"):
        x,y,_=load_ut_har(RAW/"UT-HAR"/"UT_HAR",split)
        print(f"  {split:5s} X={x.shape} target={dict(Counter(TARGET_NAMES[int(v)] for v in y))}")
    print("CSI-HAR-3room (window=250, stride=125, purity>=0.9)")
    items=iter_csi_har_windows(RAW/"CSI-HAR-3room")
    targets,rooms=Counter(),Counter()
    for item in items: targets[TARGET_NAMES[item.y]]+=1; rooms[item.room]+=1
    print(f"  target={dict(targets)}\n  room={dict(rooms)}\n  note: this dataset has no fall class")
if __name__=="__main__": main()
