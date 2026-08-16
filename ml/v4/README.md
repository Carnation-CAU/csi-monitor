# v4 고전 머신러닝 모델 비교

공개 ESP-Fi HAR 데이터에서 다음 모델을 같은 조건으로 비교한다.

- Random Forest
- HistGradientBoosting
- RBF SVM

각 모델은 다음 네 조합으로 평가한다.

1. 전체 행동 학습 + 기존 통계 특징
2. 전체 행동 학습 + 통계 특징·DTW 거리
3. 점프·스쿼트 제외 학습 + 기존 통계 특징
4. 점프·스쿼트 제외 학습 + 통계 특징·DTW 거리

참가자 분리(LOPO)와 환경 분리(LOEO)를 모두 수행하며, 점프·스쿼트 제외 모델은
두 행동을 별도로 입력해 낙상 오탐률도 기록한다.

```powershell
ml\.venv\Scripts\python.exe -m unittest ml\v4\test_train_models.py
ml\.venv\Scripts\python.exe ml\v4\train_models.py
```

상세 결과는 `RESULTS.md`, 실행 산출물은 Git에서 제외되는 `output/`에 저장된다.

