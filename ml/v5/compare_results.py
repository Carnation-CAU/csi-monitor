"""Combine completed v5 summaries into one sortable CSV."""
from __future__ import annotations
import csv,json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def main():
    rows=[]
    for path in sorted((HERE/"output").glob("*/summary.json")):
        summary=json.loads(path.read_text(encoding="utf-8")); config=json.loads((path.parent/"config.json").read_text(encoding="utf-8"))
        row={"run":path.parent.name,"model":config["model"],"protocol":config["protocol"],"best_epoch":summary["best_epoch"]}
        row.update({f"val_{k}":v for k,v in summary["validation"].items()})
        row.update({f"test_{k}":v for k,v in summary["test"].items()})
        rows.append(row)
    if not rows: raise SystemExit("no completed summary.json below output")
    rows.sort(key=lambda r:r["val_macro_f1"],reverse=True)
    target=HERE/"output"/"baseline_comparison.csv"
    with target.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    print("model       val_macro_f1 test_macro_f1 fall_recall walking_f1")
    for r in rows: print(f"{r['model']:12s} {r['val_macro_f1']:.4f}       {r['test_macro_f1']:.4f}        {r['test_fall_recall']:.4f}      {r['test_walking_f1']:.4f}")
    print("saved:",target)
if __name__=="__main__": main()

