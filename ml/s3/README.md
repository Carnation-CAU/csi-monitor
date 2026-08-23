# ESP32-S3 Recall-first ML pipeline

이 폴더는 공개 ESP32-C3 모델을 교체할 S3 실측 IQ 전용 학습·평가 경로다.

- `dataset.py`: session IQ, fixed-time resampling, relative amplitude, Δ/Δ², phase delta, `[-2,+3]초` overlap window와 bounded augmentation
- `features.py`: XGBoost용 변화량/energy/peak/correlation/spectral/post-event 특징
- `models.py`: TCN, CNN+GRU, lightweight 2D CNN, focal loss
- `training.py`: train/threshold-validation/locked-test group 분리와 후보 학습
- `evaluation.py`: Recall/Precision/F1/FN/FP, confusion matrix 재료, PR/ROC와 physical-event latency
- `replay_compare.py`: 배포 전후 규칙을 같은 raw S3 session에 replay

## 데이터 감사

```bash
PYTHONPATH=gateway/src:. .venv/bin/python -m ml.s3.training
```

기본 요건은 S3 fall 20건, known room 3개, known person 3명, channel 2개와 non-fall
session이다. 이는 충분한 통계 요건이 아니라 실수로 2~3개 session을 학습·test한 뒤
성능으로 발표하는 일을 막는 최소 guard다. 부족하면 JSON에 `publishable: false`를
쓰고 exit 2로 종료한다. `--allow-smoke-test`도 3개 known split group이 없으면 실제
학습하지 않으며, smoke 결과는 배포/성능 주장에 사용할 수 없다.

## 후보 실험

training 의존성은 `pip install -e '.[ml-training]'`로 설치한다.

```bash
python -m ml.s3.training --model xgboost --group-key room_id
python -m ml.s3.training --model tcn --group-key person_id
python -m ml.s3.training --model cnn_gru --group-key channel
python -m ml.s3.training --model cnn2d --group-key room_id
```

각 fold는 서로 다른 group을 train, threshold validation, locked test에 둔다.
threshold는 validation에서 target Fall Recall 95%를 만족하는 후보 중 Precision이
가장 높은 값으로 선택한다. locked test score는 threshold/model 선택에 사용하지 않는다.

## 현재 상태

2026-08-24 로컬 inventory는 유효 raw-IQ session 3개, fall 2건, empty room 1건,
known person 0명이다. 따라서 새 S3 checkpoint 학습과 일반화 평가는 차단되어 있다.
현재 runtime의 C3 checkpoint는 임시 auxiliary evidence이며, S3 grouped locked test를
통과한 checkpoint가 생길 때만 `ml/v_main` 교체 절차를 진행한다.
