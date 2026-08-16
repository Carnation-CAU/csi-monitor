"""Train and evaluate leakage-safe ESP-Fi CNN baselines."""
from __future__ import annotations
import argparse,csv,json,random,time
from collections import Counter
from pathlib import Path
import numpy as np
import torch
from sklearn.metrics import accuracy_score,balanced_accuracy_score,confusion_matrix,f1_score,precision_recall_fscore_support
from torch import nn
from torch.utils.data import DataLoader
from dataset import EspFiDataset,LABEL_NAMES,index_espfi,split_records
from models import make_model

HERE=Path(__file__).resolve().parent
DEFAULT_DATA=HERE.parent/"dataset"/"raw"/"ESP-Fi-HAR-full"

def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument("--model",choices=["simple_cnn","resnet18"],required=True)
    p.add_argument("--data",type=Path,default=DEFAULT_DATA)
    p.add_argument("--protocol",choices=["participant","environment"],default="participant")
    p.add_argument("--output",type=Path,default=HERE/"output")
    p.add_argument("--epochs",type=int,default=60); p.add_argument("--patience",type=int,default=10)
    p.add_argument("--batch-size",type=int,default=16); p.add_argument("--lr",type=float,default=1e-3)
    p.add_argument("--weight-decay",type=float,default=1e-4); p.add_argument("--dropout",type=float,default=.3)
    p.add_argument("--workers",type=int,default=0); p.add_argument("--seed",type=int,default=42)
    p.add_argument("--no-augment",action="store_true"); p.add_argument("--require-cuda",action="store_true")
    p.add_argument("--smoke-test",action="store_true",help="one epoch with at most 64 samples per split")
    return p.parse_args()

def seed_all(seed):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark=False; torch.backends.cudnn.deterministic=True

def metrics(actual,predicted):
    precision,recall,f1,_=precision_recall_fscore_support(actual,predicted,labels=range(3),zero_division=0)
    return {"accuracy":float(accuracy_score(actual,predicted)),"balanced_accuracy":float(balanced_accuracy_score(actual,predicted)),
            "macro_f1":float(f1_score(actual,predicted,average="macro")),"fall_precision":float(precision[0]),
            "fall_recall":float(recall[0]),"fall_f1":float(f1[0]),"walking_f1":float(f1[1])}

def run_epoch(model,loader,criterion,device,optimizer=None,scaler=None):
    training=optimizer is not None; model.train(training); total_loss=0.; actual=[]; predicted=[]
    for x,y,_ in loader:
        x=x.to(device,non_blocking=True); y=y.to(device,non_blocking=True)
        if training: optimizer.zero_grad(set_to_none=True)
        enabled=device.type=="cuda"
        with torch.amp.autocast(device_type=device.type,enabled=enabled):
            logits=model(x); loss=criterion(logits,y)
        if training:
            scaler.scale(loss).backward(); scaler.step(optimizer); scaler.update()
        total_loss+=loss.item()*len(y); actual.extend(y.detach().cpu().tolist()); predicted.extend(logits.argmax(1).detach().cpu().tolist())
    return {"loss":total_loss/len(loader.dataset),**metrics(actual,predicted)},actual,predicted

def save_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)

def main():
    args=parse_args(); seed_all(args.seed)
    device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if args.require_cuda and device.type!="cuda": raise SystemExit("CUDA requested but torch.cuda.is_available() is False")
    records=index_espfi(args.data); splits=split_records(records,args.protocol)
    if args.smoke_test:
        args.epochs=1; args.patience=1; splits={k:v[:64] for k,v in splits.items()}
    stamp=time.strftime("%Y%m%d-%H%M%S"); run_dir=args.output/f"{args.model}-{args.protocol}-{stamp}"
    run_dir.mkdir(parents=True,exist_ok=False)
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    config.update({"device":str(device),"torch":torch.__version__,"split_sizes":{k:len(v) for k,v in splits.items()},"labels":LABEL_NAMES})
    (run_dir/"config.json").write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding="utf-8")
    loaders={name:DataLoader(EspFiDataset(rows,augment=name=="train" and not args.no_augment),batch_size=args.batch_size,
        shuffle=name=="train",num_workers=args.workers,pin_memory=device.type=="cuda",persistent_workers=args.workers>0)
        for name,rows in splits.items()}
    counts=Counter(r.label for r in splits["train"]); weights=torch.tensor([len(splits["train"])/(3*counts[i]) for i in range(3)],dtype=torch.float32,device=device)
    model=make_model(args.model,3,args.dropout).to(device); criterion=nn.CrossEntropyLoss(weight=weights)
    optimizer=torch.optim.AdamW(model.parameters(),lr=args.lr,weight_decay=args.weight_decay)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,mode="max",factor=.5,patience=3)
    scaler=torch.amp.GradScaler("cuda",enabled=device.type=="cuda")
    print(f"device={device} model={args.model} parameters={sum(p.numel() for p in model.parameters()):,} splits={config['split_sizes']}")
    history=[]; best=-1.; stale=0
    for epoch in range(1,args.epochs+1):
        train_m,_,_=run_epoch(model,loaders["train"],criterion,device,optimizer,scaler)
        with torch.inference_mode(): val_m,_,_=run_epoch(model,loaders["val"],criterion,device)
        scheduler.step(val_m["macro_f1"]); row={"epoch":epoch,"lr":optimizer.param_groups[0]["lr"],**{f"train_{k}":v for k,v in train_m.items()},**{f"val_{k}":v for k,v in val_m.items()}}
        history.append(row); print(f"epoch={epoch:03d} train_loss={train_m['loss']:.4f} val_macro_f1={val_m['macro_f1']:.4f} fall_recall={val_m['fall_recall']:.4f}")
        if val_m["macro_f1"]>best:
            best=val_m["macro_f1"]; stale=0
            torch.save({"model_state":model.state_dict(),"model_name":args.model,"labels":LABEL_NAMES,"config":config,"epoch":epoch,"val_metrics":val_m},run_dir/"best.pt")
        else:
            stale+=1
            if stale>=args.patience: print(f"early stopping at epoch {epoch}"); break
    save_csv(run_dir/"history.csv",history)
    checkpoint=torch.load(run_dir/"best.pt",map_location=device,weights_only=False); model.load_state_dict(checkpoint["model_state"])
    with torch.inference_mode(): test_m,actual,predicted=run_epoch(model,loaders["test"],criterion,device)
    matrix=confusion_matrix(actual,predicted,labels=range(3))
    save_csv(run_dir/"confusion_matrix.csv",[{"actual":LABEL_NAMES[i],**{LABEL_NAMES[j]:int(matrix[i,j]) for j in range(3)}} for i in range(3)])
    summary={"best_epoch":checkpoint["epoch"],"validation":checkpoint["val_metrics"],"test":test_m,"run_dir":str(run_dir)}
    (run_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
