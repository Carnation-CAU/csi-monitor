# v1.1 생활환경 중심 행동 실험

ESP-Fi HAR에서 독거노인의 일상생활에 나타날 가능성이 낮은 `jump`, `squat`을
학습과 주 평가에서 제외했을 때 성능이 달라지는지 검증한다.

동일한 test 표본에 대해 다음 모델을 비교한다.

1. 기존처럼 7개 행동을 모두 학습한 모델
2. `jump`, `squat`을 제외한 5개 행동만 학습한 모델

주 평가는 `fall`, `walk`, `run`, `turn`, `arm_wave`만 사용한다. 제외한 두 행동은
완전히 버리지 않고, 학습하지 않은 모델에 별도로 입력해 낙상 오탐률을 확인한다.

```powershell
python ml\v1_1\train_focused.py
python -m unittest ml\v1_1\test_train_focused.py
```

기존 `ml/v1/output/features.csv`가 있으면 이를 읽어 빠르게 실행한다. 없으면 공개
원본 데이터에서 동일한 v1 특징을 다시 추출한다. 상세 결과는 `RESULTS.md`, 실행
산출물은 Git에서 제외되는 `output/`에 저장된다.

