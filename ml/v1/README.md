# v1 계층형 고전 머신러닝

딥러닝 없이 ESP-Fi HAR 전체 4개 환경을 사용해 다음을 비교한다.

1. 7개 원래 행동을 학습한 뒤 3개 목표 레이블로 병합
2. `fall vs non-fall`과 `walking vs other`를 나눈 계층형 분류
3. 낙상 확률과 이벤트 후 무활동 점수를 결합한 계층형 분류

평가는 사람 일반화(LOPO)와 환경 일반화(LOEO)를 분리한다. 무활동 및 확률
임계값은 각 test fold를 제외한 train 내부 교차검증으로만 선택한다.

```powershell
python ml\v1\train_hierarchical.py
```

의존성은 `ml/v0/requirements.txt`와 같다. 상세 산출물은 Git에서 제외되는
`ml/v1/output/`에 저장된다.

