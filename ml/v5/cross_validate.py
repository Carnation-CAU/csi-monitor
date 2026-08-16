"""Run 3 CNN backbones over 3 public CSI datasets with four folds each."""
from __future__ import annotations
import argparse,csv,json,random,time
from collections import Counter
from pathlib import Path
import numpy as np
import torch
from sklearn.metrics import accuracy_score,balanced_accuracy_score,confusion_matrix,f1_score,precision_recall_fscore_support
from torch import nn
from torch.utils.data import DataLoader
try:
    from .data_sources import PublicCsiDataset,load_spec
    from .models import make_model
    from .train import seed_all
except ImportError:
    from data_sources import PublicCsiDataset,load_spec
    from models import make_model
    from train import seed_all

HERE=Path(__file__).resolve().parent
DATASETS=("espfi","ut_har","csi_har")
MODELS=("simple_cnn","resnet18","efficientnet_b0")

def args_parser():
    p=argparse.ArgumentParser()
    p.add_argument("--datasets",nargs="+",choices=DATASETS,default=list(DATASETS))
    p.add_argument("--models",nargs="+",choices=MODELS,default=list(MODELS))
    p.add_argument("--fold",type=int,choices=[1,2,3,4])
    p.add_argument("--output",type=Path,default=HERE/"output"/"cross_validation")
    p.add_argument("--results-file",type=Path,default=HERE/"RESULTS.md")
    p.add_argument("--epochs",type=int,default=60); p.add_argument("--patience",type=int,default=10)
    p.add_argument("--batch-size",type=int,default=16); p.add_argument("--workers",type=int,default=0)
    p.add_argument("--lr",type=float,default=1e-3); p.add_argument("--weight-decay",type=float,default=1e-4)
    p.add_argument("--dropout",type=float,default=.3); p.add_argument("--seed",type=int,default=42)
    p.add_argument("--require-cuda",action="store_true"); p.add_argument("--smoke-test",action="store_true")
    return p.parse_args()

def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)

def limited(samples,maximum=64):
    result=[]; by_label={label:[s for s in samples if s.label==label] for label in sorted({s.label for s in samples})}
    while len(result)<maximum and any(by_label.values()):
        for label in by_label:
            if by_label[label] and len(result)<maximum: result.append(by_label[label].pop(0))
    return result

def epoch_metrics(actual,predicted,label_names):
    precision,recall,f1,_=precision_recall_fscore_support(actual,predicted,labels=range(len(label_names)),zero_division=0)
    result={"accuracy":float(accuracy_score(actual,predicted)),"balanced_accuracy":float(balanced_accuracy_score(actual,predicted)),
        "macro_f1":float(f1_score(actual,predicted,labels=range(len(label_names)),average="macro",zero_division=0))}
    for i,name in enumerate(label_names):
        result[f"{name}_precision"]=float(precision[i]); result[f"{name}_recall"]=float(recall[i]); result[f"{name}_f1"]=float(f1[i])
    return result

def run_epoch(model,loader,criterion,device,label_names,optimizer=None,scaler=None):
    training=optimizer is not None; model.train(training); total=0.; actual=[]; predicted=[]
    for x,y,_ in loader:
        x=x.to(device,non_blocking=True); y=y.to(device,non_blocking=True)
        if training: optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast(device_type=device.type,enabled=device.type=="cuda"):
            logits=model(x); loss=criterion(logits,y)
        if training: scaler.scale(loss).backward(); scaler.step(optimizer); scaler.update()
        total+=loss.item()*len(y); actual.extend(y.detach().cpu().tolist()); predicted.extend(logits.argmax(1).detach().cpu().tolist())
    return {"loss":total/len(loader.dataset),**epoch_metrics(actual,predicted,label_names)},actual,predicted

def fit_fold(spec,fold,model_name,args,device):
    run_dir=args.output/spec.name/model_name/f"fold-{fold.number}"
    summary_path=run_dir/"summary.json"
    if summary_path.exists() and not args.smoke_test:
        print("skip completed",run_dir); return json.loads(summary_path.read_text(encoding="utf-8"))
    run_dir.mkdir(parents=True,exist_ok=True)
    epochs=1 if args.smoke_test else args.epochs; patience=1 if args.smoke_test else args.patience
    train_samples=limited(fold.train) if args.smoke_test else fold.train
    val_samples=limited(fold.val) if args.smoke_test else fold.val
    test_samples=limited(fold.test) if args.smoke_test else fold.test
    loaders={name:DataLoader(PublicCsiDataset(rows,name=="train"),batch_size=args.batch_size,shuffle=name=="train",
        num_workers=args.workers,pin_memory=device.type=="cuda",persistent_workers=args.workers>0)
        for name,rows in {"train":train_samples,"val":val_samples,"test":test_samples}.items()}
    num_classes=len(spec.label_names); counts=Counter(s.label for s in train_samples)
    if set(counts)!=set(range(num_classes)): raise ValueError(f"fold lacks a class: {counts}")
    weights=torch.tensor([len(train_samples)/(num_classes*counts[i]) for i in range(num_classes)],dtype=torch.float32,device=device)
    model=make_model(model_name,num_classes,args.dropout).to(device); criterion=nn.CrossEntropyLoss(weight=weights)
    optimizer=torch.optim.AdamW(model.parameters(),lr=args.lr,weight_decay=args.weight_decay)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,mode="max",factor=.5,patience=3)
    scaler=torch.amp.GradScaler("cuda",enabled=device.type=="cuda"); history=[]; best=-1.; stale=0
    print(f"START dataset={spec.name} model={model_name} fold={fold.number} sizes={len(train_samples)}/{len(val_samples)}/{len(test_samples)}")
    for epoch in range(1,epochs+1):
        train_m,_,_=run_epoch(model,loaders["train"],criterion,device,spec.label_names,optimizer,scaler)
        with torch.inference_mode(): val_m,_,_=run_epoch(model,loaders["val"],criterion,device,spec.label_names)
        scheduler.step(val_m["macro_f1"]); row={"epoch":epoch,**{f"train_{k}":v for k,v in train_m.items()},**{f"val_{k}":v for k,v in val_m.items()}}
        history.append(row); print(f"  epoch={epoch:03d} val_macro_f1={val_m['macro_f1']:.4f} {spec.label_names[0]}_recall={val_m[spec.label_names[0]+'_recall']:.4f}")
        if val_m["macro_f1"]>best:
            best=val_m["macro_f1"]; stale=0
            torch.save({"model_state":model.state_dict(),"model_name":model_name,"labels":spec.label_names,
                "input_frames":950,"epoch":epoch,"val_metrics":val_m},run_dir/"best.pt")
        else:
            stale+=1
            if stale>=patience: break
    write_csv(run_dir/"history.csv",history)
    checkpoint=torch.load(run_dir/"best.pt",map_location=device,weights_only=False); model.load_state_dict(checkpoint["model_state"])
    with torch.inference_mode(): test_m,actual,predicted=run_epoch(model,loaders["test"],criterion,device,spec.label_names)
    matrix=confusion_matrix(actual,predicted,labels=range(num_classes))
    write_csv(run_dir/"confusion_matrix.csv",[{"actual":spec.label_names[i],**{spec.label_names[j]:int(matrix[i,j]) for j in range(num_classes)}} for i in range(num_classes)])
    summary={"dataset":spec.name,"model":model_name,"fold":fold.number,"labels":spec.label_names,"note":spec.note,
        "sizes":{"train":len(train_samples),"val":len(val_samples),"test":len(test_samples)},"best_epoch":checkpoint["epoch"],
        "validation":checkpoint["val_metrics"],"test":test_m}
    summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return summary

def aggregate(output: Path,results_file: Path):
    summaries=[json.loads(p.read_text(encoding="utf-8")) for p in output.glob("*/*/fold-*/summary.json")]
    rows=[]
    for dataset in DATASETS:
        for model in MODELS:
            selected=[s for s in summaries if s["dataset"]==dataset and s["model"]==model]
            if not selected: continue
            row={"dataset":dataset,"model":model,"folds":len(selected)}
            common=("accuracy","balanced_accuracy","macro_f1")
            specific=("fall_recall","fall_f1","walking_f1") if dataset!="csi_har" else ("walking_recall","walking_f1","other_motion_f1")
            for metric in common+specific:
                values=np.asarray([s["test"][metric] for s in selected],dtype=float)
                row[f"{metric}_mean"]=float(values.mean()); row[f"{metric}_std"]=float(values.std())
            rows.append(row)
    if rows:
        write_csv(output/"cv_summary.csv",rows)
        lines=["# v5 공개 CSI CNN 교차검증 결과","","> 이 파일은 `cross_validate.py`가 완료된 fold를 기준으로 자동 갱신한다.","",
            "| 데이터셋 | 모델 | folds | Macro-F1 | Balanced accuracy | 주요 클래스 recall |","|---|---|---:|---:|---:|---:|"]
        for row in rows:
            recall_key="walking_recall" if row["dataset"]=="csi_har" else "fall_recall"
            lines.append(f"| {row['dataset']} | {row['model']} | {row['folds']} | {row['macro_f1_mean']:.4f} ± {row['macro_f1_std']:.4f} | {row['balanced_accuracy_mean']:.4f} ± {row['balanced_accuracy_std']:.4f} | {row[recall_key+'_mean']:.4f} ± {row[recall_key+'_std']:.4f} |")
        lines.extend(["","CSI-HAR의 주요 recall은 walking이며 다른 두 데이터셋은 fall이다. CSI-HAR에는 fall 라벨이 없으므로 절대 점수를 3분류 데이터셋과 직접 비교하지 않는다.",""])
        results_file.parent.mkdir(parents=True,exist_ok=True)
        results_file.write_text("\n".join(lines),encoding="utf-8")
    return rows

def main():
    args=args_parser(); seed_all(args.seed); device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if args.require_cuda and device.type!="cuda": raise SystemExit("CUDA requested but unavailable")
    if args.smoke_test:
        args.output=args.output/"smoke"
        args.results_file=args.output/"RESULTS.md"
    for dataset_name in args.datasets:
        spec=load_spec(dataset_name,args.seed)
        for model_name in args.models:
            for fold in spec.folds:
                if args.fold and fold.number!=args.fold: continue
                seed_all(args.seed+fold.number); fit_fold(spec,fold,model_name,args,device)
    rows=aggregate(args.output,args.results_file)
    print(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
