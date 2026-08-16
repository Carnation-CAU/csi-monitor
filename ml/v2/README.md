# v2 DTW 시계열 분류 실험

v1의 45개 통계 특징에서 사라진 시간 순서가 행동 분류에 도움이 되는지 확인한다.

- v2-A: 행동별 대표 파형과의 DTW 거리만으로 분류
- v2-B: 기존 45개 통계 특징과 행동별 DTW 거리를 결합해 로지스틱 회귀

각 방법은 다음 두 학습 구성을 모두 평가한다.

- 전체 행동 모델: `jump`, `squat` 포함
- 생활환경 중심 모델: `jump`, `squat` 제외

주 평가는 두 모델 모두 같은 5개 행동 test 표본에서 수행한다. 제외 행동은
생활환경 중심 모델의 별도 안전성 평가에 사용한다.

```powershell
ml\.venv\Scripts\python.exe -m unittest ml\v2\test_train_dtw.py
ml\.venv\Scripts\python.exe ml\v2\train_dtw.py
```

상세 결과는 `RESULTS.md`, 실행 산출물은 Git에서 제외되는 `output/`에 저장된다.

