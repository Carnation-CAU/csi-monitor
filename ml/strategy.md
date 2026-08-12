# 행동 분류 전략과 버전 비교 계획

작성일: 2026-08-11

## 목표

ESP32-S3 RX에서 수집한 시계열 또는 공개 Wi-Fi CSI 데이터에서 움직임 이벤트를
찾고, 해당 이벤트를 행동으로 분류한다.

```text
연속 신호
  → 움직임 이벤트 시작/종료 탐지
  → 행동 분류
  → normal / unknown / fall_suspected 위험도 판정
```

초기 분류 대상은 데이터가 확보된 범위에서 작게 시작한다.

```text
walking
lie_down 또는 posture_transition
get_up
other_motion
unknown
```

모든 움직임을 알려진 행동 중 하나로 강제하지 않는다. 충분히 유사하지 않은
입력은 `unknown`으로 남긴다. 낙상은 처음부터 확정 클래스처럼 다루지 않고
행동 분류 결과, 변화 강도와 이후 무활동을 결합한 `fall_suspected`로 다룬다.

## 공통 원칙

1. 행동 분류 작업은 `ml/` 안에서만 수행하고 기존 코드는 수정하지 않는다.
2. 같은 데이터와 같은 split으로 모든 전략을 비교한다.
3. window를 무작위 분할하지 않고 세션·참가자·환경 단위로 분할한다.
4. test 데이터는 모델·threshold 선택에 사용하지 않는다.
5. accuracy뿐 아니라 Macro-F1과 행동별 recall을 기록한다.
6. 공개 데이터 모델과 우리 ESP32 모델의 성능을 구분해 기록한다.
7. 공개 CSI의 파생값을 Espressif의 `jitter`와 동일하다고 부르지 않는다.
8. 단순한 전략이 충분히 작동하면 복잡한 모델을 선택하지 않는다.

## 전략 우선순위

우선순위는 현재 데이터 규모에서의 성공 가능성, 구현 난이도, 설명 가능성,
실시간 적용 가능성을 함께 고려했다.

| 버전 | 전략 | 성공 가능성 | 목적 |
|---|---|---:|---|
| v0 | 데이터/규칙 기준선 | 높음 | 신호와 라벨이 실제로 분리되는지 확인 |
| v1 | 상태 머신 + 수동 특징 + Random Forest | 가장 높음 | 첫 실용 분류 기준선 |
| v2 | 상태 머신 + DTW | 중상 | 시계열 모양과 행동 속도 차이 검증 |
| v3 | Gradient Boosting 또는 SVM | 중상 | 수동 특징 모델의 성능 상한 비교 |
| v4 | 1D CNN | 중상, 데이터 의존 | raw 시계열의 국소 패턴 학습 |
| v5 | 이상 탐지 결합 | 낙상 후보에 유망 | 미지 행동과 위험 이벤트 분리 |
| v6 | GRU/LSTM | 보통 | 긴 시간 순서가 필요할 때만 비교 |
| v7 | Transformer/대규모 사전학습 | 현재는 낮음 | 충분한 공개·자체 데이터 확보 후 검토 |

## v0. 데이터와 규칙 기준선

### 목적

모델을 학습하기 전에 행동별 신호 차이와 이벤트 경계를 확인한다. 이 단계가
실패하면 복잡한 모델로 넘어가지 않고 데이터 수집과 라벨을 먼저 수정한다.

### 입력 후보

- 우리 데이터: `wander`, `jitter`, `move_threshold`, `move_status`
- 공개 데이터: subcarrier amplitude에서 만든 `motion_energy`, 시간 차분과
  rolling dispersion

### 확인할 값

- 이벤트 지속시간
- 최대 변화량과 최대 기울기
- peak 개수
- threshold 초과 비율과 연속 초과 길이
- 전반부/후반부 평균 차이
- 이벤트 종료 후 정지시간
- 패킷 손실과 표본률 변화

### 규칙 예시

```text
반복 peak + 비교적 긴 움직임
  → walking 후보

단일 전환 peak + 이후 정지
  → posture_transition 후보

매우 큰 변화 + 이후 긴 무활동
  → fall_suspected 후보
```

### 통과 조건

- 행동별 분포와 대표 시계열을 시각적으로 설명할 수 있다.
- 이벤트 시작과 종료가 대부분의 세션에서 합리적으로 잘린다.
- 단순 규칙의 confusion matrix를 만들 수 있다.

## v1. 상태 머신 + Random Forest — 첫 추천 모델

### 구조

```text
연속 신호
  → 상태 머신(IDLE / MOVING / POST_MOTION)
  → 이벤트별 고정 길이 특징
  → Random Forest
  → label + confidence 또는 unknown
```

### 추천 이유

- 작은 데이터에서도 비교적 안정적이다.
- 비선형 특징 조합을 처리한다.
- 스케일링에 덜 민감하다.
- 특징 중요도와 오분류 원인을 확인하기 쉽다.
- 학습과 CPU 추론 비용이 낮다.

### 특징 후보

- 평균, 표준편차, 중앙값, 최댓값, 범위와 분위수
- 평균 절대 변화량과 최대 상승/하강 기울기
- peak 개수, peak 크기와 위치
- 이벤트 지속시간
- threshold 초과 비율과 최대 연속 초과 길이
- 전반부/후반부 차이
- 이벤트 이후 정지시간
- 저주파/고주파 에너지

### unknown 처리

최대 클래스 확률이 validation에서 정한 기준보다 낮으면 `unknown`으로 반환한다.
Random Forest 확률은 실제 신뢰도와 같지 않으므로 필요하면 validation 데이터로
확률 보정을 비교한다.

## v2. 상태 머신 + DTW

### 구조

행동별 대표 파형과 새 이벤트의 Dynamic Time Warping 거리를 비교한다.

```text
새 이벤트
  → 길이/크기 정규화
  → 행동별 여러 template과 DTW 거리 계산
  → 최근접 행동 또는 unknown
```

### 추천 이유

- 행동 속도가 달라도 시계열 모양을 비교할 수 있다.
- 학습 데이터가 적어도 시작할 수 있다.
- 어떤 기준 파형과 비슷했는지 설명 가능하다.

### 한계

- 공간과 사람 변화에 민감할 수 있다.
- template 수가 커지면 추론 비용이 증가한다.
- raw 고차원 CSI에는 차원 축소나 대표 motion-energy 채널이 필요하다.

### 역할

Random Forest와 다른 관점의 기준선으로 사용한다. DTW가 더 좋으면 행동의
절댓값보다 시간적 모양이 중요하다는 근거가 된다.

## v3. Gradient Boosting 또는 SVM

Random Forest와 동일한 수동 특징을 사용한다.

### 후보

- HistGradientBoosting
- XGBoost 또는 LightGBM(추가 의존성이 허용될 때)
- RBF SVM

### 진행 조건

- v1의 데이터 파이프라인과 split이 검증돼 있어야 한다.
- Random Forest의 혼동 원인이 특징 부족인지 모델 경계 문제인지 구분할 수 있어야 한다.

이 모델의 성능이 v1보다 의미 있게 높지 않으면 Random Forest를 유지한다.

## v4. 1D CNN — 첫 딥러닝 후보

### 입력

```text
batch x channel x time
```

채널은 다음 두 경로를 별도로 시험한다.

- 공개 데이터: subcarrier amplitude 또는 차원 축소된 amplitude
- 우리 데이터: `wander`, `jitter`, `jitter-threshold`, status 등의 시계열

### 추천 이유

- 행동의 짧은 peak와 반복 패턴을 직접 학습한다.
- RNN보다 학습과 추론이 빠르다.
- ESP-Fi HAR 같은 고정 길이 amplitude 배열에 적용하기 쉽다.

### 진행 조건

- 참가자/환경 분리 후에도 충분한 train 표본이 있어야 한다.
- v1보다 행동별 Macro-F1 또는 공간 일반화가 의미 있게 개선돼야 한다.
- 모델이 장치 또는 데이터셋 출처만 구분하지 않는지 확인해야 한다.

공개 데이터와 ESP32 데이터를 단순 혼합한 무작위 split은 금지한다.

## v5. 이상 탐지와 위험도 결합

낙상 데이터는 적고 안전하게 반복 수집하기 어렵다. 따라서 정상 행동 분류와
이상 탐지를 분리해 비교한다.

### 후보

- 정상 행동 prototype과의 거리
- One-Class SVM
- Isolation Forest
- 작은 autoencoder의 reconstruction error

### 위험도 규칙

```text
알려진 정상 행동과 낮은 유사도
+ 큰 변화
+ 이후 긴 무활동
  → fall_suspected
```

이 결과는 낙상 확정이 아니라 확인이 필요한 이벤트다. 빠르게 앉기, 눕기,
물건 줍기를 주요 음성 사례로 평가한다.

## v6. GRU/LSTM

다음 조건에서만 시험한다.

- 1D CNN이 행동 전후의 긴 순서를 충분히 표현하지 못한다.
- 이벤트 길이가 다양하고 고정 길이 변환에서 정보 손실이 확인된다.
- 충분한 자체 데이터가 확보됐다.

초기에는 LSTM보다 파라미터가 적은 GRU를 먼저 비교한다. 작은 데이터에서
Random Forest나 1D CNN보다 성능이 불안정하면 채택하지 않는다.

## v7. Transformer와 공개 데이터 사전학습

현재 우선순위는 가장 낮다. 여러 공개 데이터셋을 공통 amplitude 표현으로
정리하고 자체 ESP32 raw CSI를 확보한 뒤 검토한다.

가능한 방향:

- masked time/subcarrier reconstruction
- contrastive learning
- 공개 CSI encoder 사전학습 후 자체 데이터 fine-tuning
- source dataset 또는 장치 domain을 분리한 평가

모델 크기보다 다른 장치·공간으로의 전이가 실제로 개선되는지가 선택 기준이다.

## 버전 공통 비교 기준

각 버전은 아래 항목을 같은 형식으로 기록한다.

### 데이터 버전

- 데이터셋 이름과 원본 버전
- 포함한 참가자, 환경, 행동과 세션 수
- 라벨 매핑 버전
- 전처리 설정과 입력 길이
- train/validation/test 그룹 목록

### 성능

- accuracy
- Macro-F1
- 행동별 precision, recall, F1
- confusion matrix
- unknown 비율
- 잘못된 `fall_suspected` 횟수
- inference latency

### 일반화

- 미참여 참가자 test
- 미사용 환경 또는 공간 test
- 가능하면 다른 장치 데이터 test

### 재현성

- random seed
- 코드 버전
- 모델 파라미터
- 학습 시간과 실행 환경
- 모델 파일과 결과 파일의 경로

## 모델 선택 규칙

최종 선택은 최고 accuracy 하나로 결정하지 않는다.

1. 세션·참가자·환경 누수가 없어야 한다.
2. Macro-F1이 규칙 기준선보다 높아야 한다.
3. `lie_down`, `get_up`, `walking`의 recall을 개별 확인한다.
4. `fall_suspected` 오탐을 별도로 확인한다.
5. unknown 입력을 억지로 알려진 행동으로 분류하지 않아야 한다.
6. 더 복잡한 모델은 단순 모델보다 반복 실험에서 일관된 개선이 있어야 한다.
7. 성능이 비슷하면 더 단순하고 설명 가능한 모델을 선택한다.

## 당장 진행할 순서

1. 공개 데이터 한 종류(우선 ESP-Fi HAR)의 실제 배열과 라벨을 확인한다.
2. 참가자·환경 단위 split을 고정한다.
3. v0 분석으로 행동별 대표 파형과 기본 통계를 만든다.
4. v1 Random Forest 기준선을 만든다.
5. 같은 split에서 v2 DTW를 비교한다.
6. 데이터가 충분할 때만 v4 1D CNN을 추가한다.
7. 자체 ESP32 데이터가 쌓이면 동일한 비교를 반복한다.
8. 정상 행동 기준선이 안정된 뒤 v5 낙상 의심 탐지를 결합한다.

첫 비교의 핵심은 **Random Forest 대 DTW**다. 두 방식으로 데이터와 라벨이
실제로 분리되는지 확인한 뒤 딥러닝으로 넘어간다.
