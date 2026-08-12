# v0 학습 타당성 결과

실행일: 2026-08-11

## 목표 레이블

초기 목표를 다음 3개로 단순화했다.

| ESP-Fi 원본 라벨 | v0 목표 라벨 |
|---|---|
| `walk` | `walking` |
| `fall` | `fall_suspected` |
| `arm_wave`, `jump`, `run`, `squat`, `turn` | `other_motion` |

`other_motion`은 모든 움직임을 걷기 또는 낙상 의심으로 강제하지 않기 위한 필수
거부 클래스다. 공개 데이터의 `fall`은 우리 환경의 낙상을 확정하지 않으므로
`fall_suspected`로만 표현한다.

## 데이터와 평가

- ESP-Fi HAR benchmark 처리본 scenario 3
- 총 560개: `walking` 80, `fall_suspected` 80, `other_motion` 400
- 참가자 8명, 사람당 원본 7행동 x 10회
- 입력: `CSIamp[950, 52]` (`time x subcarrier`)
- 공통 파생값: amplitude 시간 차분 기반 `motion_energy`
- 특징 45개: 통계량, peak, 자기상관, 주파수대 에너지, 10개 시간 블록
- 평가: leave-one-participant-out 8-fold
- 각 fold: 7명 490개 학습, 보지 않은 1명 70개 시험

제공 train/test에는 모든 참가자가 들어 있으므로 사람 일반화를 과대평가할 수 있다.
그 대신 참가자 한 명 전체를 test로 제외했다.

## 기준선

클래스가 불균형하므로 균등 우연 수준만으로 모델을 평가하면 안 된다.

| 기준선 | Accuracy | Macro-F1 | Balanced accuracy |
|---|---:|---:|---:|
| 균등 무작위 수준 | 33.33% | - | 33.33% |
| 전부 `other_motion` 예측 | **71.43%** | 27.78% | 33.33% |

따라서 정확도만 71.43%를 넘는 것으로는 충분하지 않다. Macro-F1, balanced
accuracy와 행동별 결과를 함께 사용한다.

## 학습 결과

| 모델 | Accuracy | 표준편차 | Macro-F1 | Balanced accuracy |
|---|---:|---:|---:|---:|
| 최근접 중심 | 41.79% | 12.24%p | 41.84% | 63.17% |
| 로지스틱 회귀 | 67.50% | 15.98%p | 65.18% | **72.17%** |
| Random Forest | **73.21%** | 12.89%p | **65.64%** | 68.17% |

Random Forest는 다수 클래스 기준선보다 정확도가 1.78%p 높고 Macro-F1은 크게
높다. 로지스틱 회귀는 전체 정확도는 다수 클래스 기준선보다 낮지만 세 클래스를
더 균형 있게 탐지한다.

## 행동별 결과

### Random Forest

| 행동 | Precision | Recall | F1 |
|---|---:|---:|---:|
| `fall_suspected` | 32.2% | 47.5% | 38.4% |
| `other_motion` | 85.3% | 77.0% | 81.0% |
| `walking` | 79.0% | 80.0% | 79.5% |

### 로지스틱 회귀

| 행동 | Precision | Recall | F1 |
|---|---:|---:|---:|
| `fall_suspected` | 27.6% | **63.8%** | 38.5% |
| `other_motion` | 88.6% | 64.0% | 74.3% |
| `walking` | 82.6% | **88.8%** | 85.5% |

Random Forest confusion matrix:

```text
actual \\ predicted  fall  other  walking
fall                    38     42        0
other                   75    308       17
walking                  5     11       64
```

로지스틱 회귀는 낙상 의심을 더 많이 잡지만 `other_motion` 400개 중 129개를
낙상 의심으로 오인한다. Random Forest도 `other_motion` 400개 중 75개를 낙상
의심으로 오인한다. 현재 상태로는 알림 오탐이 지나치게 많다.

## 사람별 변동

Random Forest의 참가자별 정확도는 45.71~87.14%다. 같은 모델과 전처리에서도
사람에 따라 성능 차이가 커서 새 사람 일반화가 안정적이라고 볼 수 없다.

## 판단

- **통과:** `walking / fall_suspected / other_motion` 3단계 학습 파이프라인이
  정상 작동하고, 공통 amplitude 특징에 분류 정보가 있다.
- **부분 통과:** `walking`은 보지 않은 참가자에서도 약 80% F1이다.
- **미통과:** `fall_suspected` F1은 약 38%이고 오탐이 많아 실사용할 수 없다.
- **미검증:** 한 환경 데이터뿐이어서 방·배치 일반화는 평가하지 못했다.

현재 최선 모델을 제품에 연결하지 않는다. v0의 목적은 가능성 확인이며 그 목적은
달성했지만, 낙상 의심 판정의 타당성은 확보되지 않았다.

## 재현

```powershell
.\.venv\Scripts\python.exe -m pip install -r ml\v0\requirements.txt
.\.venv\Scripts\python.exe ml\v0\analyze_feasibility.py
```

상세 산출물은 Git에 올리지 않는 `ml/v0/output/feasibility/`에 있다.

- `features.csv`
- `fold_metrics.csv`
- `model_summary.csv`
- 모델별 confusion matrix
- `results.json`

## 다음 실험

1. `fall`과 `other_motion`의 시간 파형을 비교해 오탐 원본 행동을 확인한다.
2. 행동 전체 950 frame 대신 실제 변화 중심 구간을 정렬/crop한다.
3. 같은 참가자 독립 split에서 DTW를 비교한다.
4. 낙상 의심은 분류 점수만 쓰지 않고 큰 변화 후 무활동 규칙을 결합한다.
5. 이후 raw `950 x 52`를 직접 입력하는 1D CNN과 비교한다.