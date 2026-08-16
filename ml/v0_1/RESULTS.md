# ESP-Fi HAR 환경 조사와 v0.1 오류 분석

실행일: 2026-08-12

## 결론

현재 공개 데이터는 우리 프로젝트와 같은 ESP32 계열의 52개 CSI amplitude를
사용하므로 **전처리·모델 후보를 탐색하는 용도**로는 유효하다. 그러나 현재
보유본은 회의실 한 환경뿐이고 ESP32-C3로 수집됐으며 시간·배치 메타데이터가
없다. 따라서 이 데이터로 얻은 성능을 ESP32-S3 실사용 성능으로 해석할 수 없다.

v0.1에서 가장 나은 작은 변경은 7개 원래 행동을 학습한 후 3개 목표 레이블로
합치는 로지스틱 회귀였다. 낙상 F1은 38.5%에서 **40.2%**로만 올랐다. 단순한
피크 정렬과 전후 에너지 특징도 의미 있는 개선을 만들지 못했다. 현재 병목은
모델 크기보다 환경·참가자 변화와 `fall`/유사 행동의 신호 중첩이다.

## 공개 데이터 수집 환경

공식 저장소와 논문 공개 페이지에서 확인되는 내용은 다음과 같다.

| 항목 | 확인 내용 |
|---|---|
| 수집 장비 | ESP32-C3 기반 저전력 노드, ESP-CSI-Tool 사용 |
| 신호 | CSI amplitude만 제공 |
| 샘플 모양 | `950 time index x 52 subcarriers` |
| 환경 | 복도, 사무실, 회의실, 실험실 4개 |
| 참가자 | 8명 |
| 행동 | run, fall, walk, turn, jump, squat, arm wave 7개 |
| 반복 | 환경·참가자·행동마다 10회 |
| 규모 | 환경마다 560개, 전체 설명상 2,240개 |
| 공식 전처리 | 샘플 하나 전체에 Z-score 정규화 |
| 라이선스 | 데이터 CC BY 4.0, 코드 MIT |

출처: [공식 GitHub 저장소](https://github.com/AutoSmartGroup/ESP-Fi-HAR),
[Ad Hoc Networks 논문 페이지](https://www.sciencedirect.com/science/article/pii/S1570870526000582)

### 현재 로컬에 있는 데이터

- 560개 파일 모두 파일명 첫 필드가 `3`: **회의실 시나리오만 존재**
- 각 행동 80개, 각 참가자 70개, 각 trial 조합 10개
- 제공 split은 참가자 1을 test, 참가자 2~8을 train으로 사용
- 모든 MAT 파일은 `CSIamp (950, 52), double` 변수 하나만 포함
- timestamp, 실제 초 단위 길이, 패킷 간격, RSSI, phase는 포함되지 않음

공식 저장소 README와 접근 가능한 논문 공개 페이지에서는 Tx-Rx 거리·높이,
LOS/NLOS, 표본률, 행동 시작/종료 규칙, 참가자 연령 등의 세부 조건을 확인하지
못했다. 이 값들은 추측해서 전처리에 넣지 않는다.

## 우리 환경과의 차이

| ESP-Fi HAR | 우리 시스템 | 영향 |
|---|---|---|
| ESP32-C3 | ESP32-S3 두 대 | RF/펌웨어 차이에 따른 domain shift 가능 |
| 회의실 한 환경만 현재 보유 | 실제 주거 공간 목표 | 방 구조·배치 변화 검증 불가 |
| 고정 길이 950 index | 연속 패킷 스트림 | 이벤트 분할과 재표본화가 추가로 필요 |
| 샘플 전체 Z-score | 온라인 기준선/동적 threshold | 절대 변화량과 실시간 정규화가 직접 호환되지 않음 |
| 원래 7개 행동 | 걷기·낙상 의심 중심 | 유사 행동을 hard negative로 활용해야 함 |

따라서 공개 데이터와 우리 데이터의 공통 표현은 `time x 52 amplitude`로 잡되,
공개 데이터의 950 index를 임의의 Hz나 초로 해석하면 안 된다.

## v0.1 평가 방법

- 참가자 한 명 전체를 test로 남기는 8-fold 검증
- 모든 샘플이 한 번씩 test가 된 out-of-fold 예측을 합쳐 지표 계산
- 목표 레이블: `walking`, `fall_suspected`, `other_motion`
- 모델: class-balanced Logistic Regression, Random Forest
- 비교 특징: 기존 45개 및 피크 위치·전후 에너지 등 시간 특징 46개 추가

v0 문서의 숫자는 fold별 지표의 평균이고, 아래 숫자는 전체 out-of-fold 예측을
합친 값이므로 Macro-F1이 소수점 수준에서 다를 수 있다.

## 전략 비교

| 학습 방식 | 모델 | Accuracy | Macro-F1 | Fall Precision | Fall Recall | Fall F1 |
|---|---|---:|---:|---:|---:|---:|
| 3-class 직접, 기존 특징 | Logistic | 67.50% | 66.11% | 27.57% | 63.75% | 38.49% |
| 3-class 직접, 기존 특징 | Random Forest | 73.21% | 66.28% | 32.20% | 47.50% | 38.38% |
| **7-class 학습 후 병합, 기존 특징** | **Logistic** | **75.54%** | **69.01%** | **34.21%** | **48.75%** | **40.21%** |
| 7-class 학습 후 병합, 기존 특징 | Random Forest | 71.43% | 63.82% | 29.91% | 43.75% | 35.53% |
| 3-class 직접, 시간 특징 추가 | Logistic | 70.54% | 67.77% | 29.09% | 60.00% | 39.18% |
| 3-class 직접, 시간 특징 추가 | Random Forest | 73.39% | 66.78% | 33.04% | 47.50% | 38.97% |
| 7-class 학습 후 병합, 시간 특징 추가 | Logistic | 74.64% | 66.58% | 28.16% | 36.25% | 31.69% |
| 7-class 학습 후 병합, 시간 특징 추가 | Random Forest | 72.32% | 65.32% | 30.25% | 45.00% | 36.18% |

`other_motion`을 하나로 뭉쳐 학습하기보다 원래 행동을 보조 레이블로 유지하는
방식은 Logistic에서 소폭 유효했다. 하지만 시간 특징 추가가 거의 효과가 없거나
오히려 나빠져, 현재의 단순 최대 피크 정렬은 다음 모델의 핵심 해법이 아니다.

## 낙상 오탐 분석

가장 높은 Fall F1 전략의 낙상 오탐은 다음과 같다.

| 실제 원래 행동 | 낙상 의심 오탐 수 / 80 |
|---|---:|
| jump | 28 |
| arm_wave | 13 |
| squat | 13 |
| turn | 12 |
| walk | 5 |
| run | 4 |

낙상 80개 중 맞춘 것은 39개이고 나머지 41개는 `other_motion`으로 빠졌다.
특히 jump가 가장 강한 hard negative다. 노인 사용 환경에서 jump 자체는 드물어도
빠르게 앉기, 주저앉기, 침대에 눕기 같은 유사 전환 동작을 별도 음성 데이터로
넣지 않으면 같은 종류의 오탐이 생길 가능성이 높다.

## 참가자 차이

가장 좋은 전략의 참가자별 낙상 recall은 **10%~100%**, precision은
**19.2%~100%**로 크게 변했다. 예를 들어 참가자 3은 낙상 10개를 전부 찾았지만
비낙상 42개를 낙상으로 오인했고, 참가자 5는 낙상 10개 중 1개만 찾았다.

이는 무작위 sample split으로 높은 점수를 만드는 것보다 참가자 분리 평가를
계속 유지해야 한다는 근거다.

## 시간 패턴 확인

15-index 이동평균 motion energy에서 가장 큰 피크 전후 100 index의 에너지 비율
중앙값은 다음과 같다.

| 행동 | peak/median | post/pre 100 | 중앙 50% 에너지 폭 |
|---|---:|---:|---:|
| fall | 1.93 | 1.02 | 0.478 |
| jump | 2.24 | 1.01 | 0.479 |
| squat | 2.10 | 1.02 | 0.475 |
| turn | 2.42 | 0.97 | 0.476 |
| walk | 5.14 | 1.08 | 0.296 |
| run | 7.32 | 1.00 | 0.285 |

`fall`, `jump`, `squat`, `turn`의 단순 시간 통계가 매우 비슷하다. 또한 fall의
post/pre가 1보다 작지 않아 이 고정 길이 샘플에서는 우리가 기대한
`충격 후 무활동`이 단순 에너지 비율로 드러나지 않는다. 낙상 후 충분한 정지
구간이 녹화되지 않았거나, 최대 에너지 피크가 실제 충격 시점이 아닐 수 있다.

## 효과적인 다음 학습안

### 1. 전체 4개 환경 확보가 최우선

딥러닝 전에 전체 2,240개를 확보하고 아래 두 평가를 분리한다.

- leave-one-participant-out: 새 사람 일반화
- leave-one-environment-out: 새 방 일반화

현재 한 환경 결과만으로 CNN을 학습하면 회의실 배경을 학습할 위험이 크다.

### 2. 계층형 분류로 변경

```text
기존 motion gate
  -> fall vs non-fall 위험 점수
       -> 비낙상이면 walking vs other_motion
  -> fall 점수 + 이벤트 이후 실제 무활동 규칙
       -> fall_suspected 또는 unknown
```

학습할 때는 원래 7개 행동을 보조 레이블로 유지한다. 최종 출력만 3개로 합쳐
`other_motion` 내부의 서로 다른 hard negative를 모델이 구분하게 한다.

### 3. 공개 데이터와 실시간 데이터의 공통 전처리

1. 52개 subcarrier amplitude 선택 및 불량 subcarrier 마스킹
2. timestamp가 있는 우리 데이터는 고정 표본률로 재표본화
3. 세션 기준 baseline 보정과 이상치 제거
4. motion gate로 이벤트 시작·종료 검출
5. 이벤트 전 구간과 종료 후 정지 구간을 함께 보존해 pad/crop
6. `변화 -> 최대 충격 후보 -> 이후 무활동`을 각각 별도 구간 특징으로 계산

공개 데이터에는 timestamp가 없으므로 2번은 normalized index로만 근사하고,
실제 시간 기반 규칙은 우리 데이터로 보정한다.

### 4. 모델 순서

1. **v1a:** 7-class 보조 학습 + Logistic/Gradient Boosting, 낙상 threshold는
   train 내부 validation participant에서 선택
2. **v1b:** 이벤트 전·후를 포함한 안전한 자체 데이터로 calibration/fine-tuning
3. **v2:** 전체 4개 환경과 자체 데이터가 확보된 뒤 작은 1D CNN/TCN 비교

Random Forest가 전체 accuracy는 높지만 이번 핵심 지표인 Fall F1에서는
Logistic보다 낫지 않았다. 따라서 다음 기본 모델은 Logistic으로 두고 복잡한
모델은 같은 split에서 명확히 개선될 때만 채택한다.

### 5. 실사용 평가 지표

낙상은 희귀 사건이므로 균형 잡힌 공개 데이터의 accuracy와 precision만으로는
충분하지 않다. 이후에는 다음을 함께 기록한다.

- 낙상 event recall
- false alarms per hour/day
- 참가자·환경별 최저 성능
- `unknown` 거부율
- 탐지 지연시간

## 산출물

재현 스크립트: `ml/v0_1/analyze_errors.py`

상세 산출물은 `ml/v0_1/output/`에 생성된다.

- `strategy_summary.csv`
- `fold_metrics.csv`
- `predictions.csv`
- `fall_false_positives_by_original_label.csv`
- `best_strategy_fall_by_participant.csv`
- `temporal_feature_medians.csv`
- 전략·모델별 confusion matrix
- `results.json`
