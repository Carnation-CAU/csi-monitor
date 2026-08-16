"""Validate the lab PC before a long training run."""
from __future__ import annotations
import argparse,platform,subprocess,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser(); p.add_argument("--require-cuda",action="store_true")
    p.add_argument("--data",type=Path,default=Path(__file__).resolve().parents[1]/"dataset"/"raw"/"ESP-Fi-HAR-full")
    args=p.parse_args()
    print("python:",sys.version.replace("\n"," ")); print("platform:",platform.platform())
    try:
        result=subprocess.run(["nvidia-smi","--query-gpu=name,memory.total,driver_version","--format=csv,noheader"],capture_output=True,text=True,check=False)
        print("nvidia-smi:",result.stdout.strip() or result.stderr.strip() or "not available")
    except FileNotFoundError: print("nvidia-smi: not found")
    try:
        import torch
        print("torch:",torch.__version__); print("torch CUDA build:",torch.version.cuda); print("CUDA available:",torch.cuda.is_available())
        if torch.cuda.is_available(): print("CUDA device:",torch.cuda.get_device_name(0)); print("VRAM GiB:",round(torch.cuda.get_device_properties(0).total_memory/1024**3,2))
        elif args.require_cuda: raise SystemExit("FAIL: CUDA-enabled PyTorch is not available")
    except ImportError:
        raise SystemExit("FAIL: PyTorch is not installed")
    files=list(args.data.rglob("*.mat"))
    print("ESP-Fi MAT files:",len(files),"at",args.data)
    if len(files)!=2240: raise SystemExit("FAIL: expected 2240 ESP-Fi MAT files")
    from scipy.io import loadmat
    shape=loadmat(files[0])["CSIamp"].shape; print("sample shape:",shape)
    if shape not in {(950,52),(52,950)}: raise SystemExit(f"FAIL: unexpected sample shape {shape}")
    ut=args.data.parent/"UT-HAR"/"UT_HAR"
    ut_files=list(ut.glob("data/X_*.csv"))+list(ut.glob("label/y_*.csv"))
    print("UT-HAR split files:",len(ut_files),"at",ut)
    if len(ut_files)!=6: raise SystemExit("FAIL: expected 6 UT-HAR split files")
    csi=args.data.parent/"CSI-HAR-3room"
    csi_sessions=list(csi.glob("room_*/*/data.csv"))
    print("CSI-HAR sessions:",len(csi_sessions),"at",csi)
    if len(csi_sessions)!=10: raise SystemExit("FAIL: expected 10 CSI-HAR sessions")
    print("PASS: environment is ready")
if __name__=="__main__": main()
