# CNN 기반 CSI 행동 분류 개발 전략

최종 수정일: 2026-08-16

## 1. 최종 목표와 시스템 책임

재실 여부는 다른 팀과 gateway가 판단한다. ML은 재실 상태에서 움직임이 감지됐을 때 최근 950프레임의 ESP32-S3 raw CSI를 받아 다음 세 행동을 분류한다.

```text
학습 라벨: fall / walking / other_motion
외부 출력: fall_suspected / walking / other_motion / unknown
```

`fall`은 학습 데이터의 행동 정답이고 `fall_suspected`는 실제 서비스의 안전한 출력 명칭이다. 모델이 의료적·법적 의미의 낙상을 확정하지 않는다.

```text
ESP32-S3 receiver
  → gateway: serial 수신, 채널·공간 보정, 재실·moving 판단
  → ML server: ring buffer, CNN 반복 추론, 예측 안정화
  → gateway/backend: 결과 표시·이벤트 기록·알림 전달
```

gateway의 `wander`, `jitter`, `someone`, `moving` 계산을 ML에서 재구현하지 않는다. CNN의 주 입력은 I/Q에서 만든 raw CSI amplitude이며 Radar 파생값은 품질 확인 또는 보조 입력 비교에만 사용한다. 모델은 서버에서 실행하므로 모델 크기를 선제적으로 제한하지 않지만 지연, 처리량, 메모리와 장치당 비용을 함께 평가한다.

## 2. 핵심 모델 전략

CSI amplitude를 `시간 × subcarrier`의 2D 신호 맵으로 보고 CNN으로 학습한다. 자연 이미지 모델을 그대로 사용한다고 가정하지 않고 CSI에 맞는 입력 stem과 전처리를 사용한다.

### 2.1 모델 후보 순서

1. **Simple CSI-CNN**: 데이터·라벨·평가 파이프라인 검증 기준선
2. **CSI-ResNet18**: 첫 주력 모델, residual block과 adaptive pooling 사용
3. **EfficientNet-B0**: 파라미터 대비 성능 비교
4. **ConvNeXt-Tiny**: 서버 GPU에서 더 큰 CNN의 성능 상한 확인

첫 정식 비교는 Simple CSI-CNN, CSI-ResNet18과 EfficientNet-B0를 모두 수행한다. ConvNeXt는 이 세 모델의 교차검증 이후에만 추가한다. Transformer, RNN, YOLO는 CNN 기준선을 이길 명확한 가설이 생긴 후 별도 버전에서 비교한다.

### 2.2 입력 채널 후보

단계를 나눠 한 번에 하나씩 추가한다.

```text
기준선: [amplitude]
후보 1: [amplitude, 시간 1차 차분]
후보 2: [amplitude, 차분, 빈방 baseline 대비 변화]
후보 3: [STFT 또는 CWT spectrogram]
```

첫 v5 모델은 amplitude 한 채널만 사용한다. 추가 채널은 같은 split에서 모든 모델에 동일하게 적용하고 ablation으로 효과를 증명한다.

## 3. 데이터셋 활용 계획

### 3.1 공통 라벨

| 공통 라벨 | 의미 |
|---|---|
| `fall` | 공개 데이터의 fall 또는 안전하게 수집한 모의 낙상 |
| `walking` | 걷기 |
| `other_motion` | 달리기, 앉기, 일어서기, 눕기, 줍기, 회전, 팔 동작 등 |

무동작·빈방 데이터는 행동 3분류에 억지로 넣지 않는다. 이는 gateway의 moving gate 검증이나 CNN의 `unknown`/OOD 평가에 별도로 사용한다.

### 3.2 ESP-Fi HAR: 첫 모델 선택 데이터

- ESP32 계열, 4개 환경, 8명, 7행동, 총 2,240개
- 입력: `950 × 52` amplitude
- `fall`, `walk`는 각각 fall, walking
- 나머지 5개 행동은 other_motion
- 용도: CNN 구조 선택, augmentation 기준선, ESP32 계열 사전학습

장비가 자체 ESP32-S3와 가장 가까우므로 첫 모델 판단은 ESP-Fi에서 수행한다.

### 3.3 UT-HAR: 독립적인 3분류 재현성 검증

- Intel 5300 계열, 입력 `250 × 90`
- fall, walk 포함
- 공식 train 3,977 / validation 496 / test 500 유지
- 용도: 선택 CNN이 한 공개 데이터에만 맞는지 확인, 별도 사전학습 비교

UT-HAR의 절대 점수를 ESP-Fi 점수와 우열처럼 해석하지 않는다. 장치와 split이 다르므로 같은 모델 구조가 각 데이터에서 안정적으로 학습되는지만 우선 확인한다.

### 3.4 CSI-HAR-3room: 공간 일반화 보조 데이터

- 3개 방의 연속 CSI, 114 subcarrier
- walking과 여러 생활 행동은 있지만 fall은 없음
- 용도: 방 교차 walking/other_motion 평가, window 절단 검증, 무라벨 사전학습

낙상이 없으므로 단독 3분류 점수를 만들거나 낙상 학습 데이터처럼 사용하지 않는다. 3분류 supervised multi-source 학습에는 ESP-Fi와 UT-HAR를 우선 사용하고 CSI-HAR는 두 클래스 보조 loss 또는 자기지도학습에서만 사용한다.

### 3.5 자체 ESP32-S3 데이터: 최종 판단 데이터

- walking: 느린·보통 걷기, 방향·속도 변화
- fall: 매트리스 위 통제된 모의 낙상
- other_motion: 빠르게 앉기, 눕기, 일어나기, 물건 줍기, 몸 돌리기, 비틀거리기, 균형 회복, 큰 팔 동작
- hard negative: 점프와 낙상 유사 동작, 가구 충격, 문 여닫기, 반려동물 등 가능한 운영 교란

사람, 방, 위치, 방향, 날짜, 의복과 장치 배치를 다양하게 한다. 같은 사람이 같은 자리에서 반복한 표본 수보다 참가자·공간 다양성을 우선한다. 실제 바닥 낙상은 수집하지 않는다.

## 4. 공통 데이터 계약과 전처리

모든 데이터 어댑터는 다음 논리 구조를 제공한다.

```text
sample_id, source_dataset, participant_id, environment_id, session_id,
original_label, target_label, sampling_rate, amplitude[T, S]
```

공개 데이터와 자체 데이터는 물리적으로 동일한 CSI가 아니다. 다음 규칙으로 차이를 관리한다.

1. 데이터셋별 원본 subcarrier 수와 시간 길이를 metadata에 보존한다.
2. 동일 CNN 구조는 adaptive pooling으로 서로 다른 `T × S`를 받을 수 있게 한다.
3. 한 batch에 여러 shape를 섞어야 하면 dataset별 batch를 번갈아 학습한다.
4. 강제 보간이 필요하면 time/subcarrier 보간 여부를 실험 변수로 기록한다.
5. 정규화는 sample별 z-score를 기준선으로 하고 train 통계·robust scaling을 비교한다.
6. test 참가자·방의 통계는 train 전처리에 사용하지 않는다.
7. 학습과 실시간 추론은 같은 I/Q 파서, subcarrier 선택, 결측 처리와 정규화 코드를 사용한다.

자체 raw CSI 처리 순서는 다음과 같다.

```text
CSI_DATA
  → timestamp·sequence 검증
  → I/Q 파싱
  → 유효 52 subcarrier 선택
  → amplitude = sqrt(I² + Q²)
  → packet gap·이상치 mask
  → 시간 기준 window 생성
  → 학습과 동일한 정규화
```

## 5. window와 v3/v3.1의 역할

공개 ESP-Fi의 `950 × 52`와 동일하게 실제 서비스도 ring buffer의 최근 950프레임을 반복 추론한다. 시간 길이는 고정하지 않고 해당 window의 실제 시작·종료 timestamp를 metadata로 기록한다. 공개 데이터 전체 샘플 성능과 실시간 sliding-window 성능을 구분한다.

### v3

- gateway의 moving 시작·종료가 실제 행동과 맞는지 검증
- 짧은 moving 단절 병합 여부 확인
- 행동 전·중·후 경계와 manifest 라벨 연결

### v3.1

- raw CSI와 Radar timestamp 정렬
- 1·2·3·4초 window와 stride 50·100·250ms 생성
- 동일 이벤트의 window를 같은 split에 고정
- 오프라인 window와 실시간 ring-buffer window의 byte/수치 동일성 테스트

행동과 겹치지 않은 준비 구간을 세션 라벨로 오염시키지 않는다. 낙상 후 정지를 관찰하기 위해 moving 종료 후 1~3초의 CSI를 버퍼에 유지한다.

## 6. 평가와 교차검증

### 6.1 ESP-Fi 모델 선택

고정 holdout은 smoke test에만 사용한다. 정식 모델 비교는 참가자 grouped 4-fold로 수행한다.

```text
Fold 1 test: participant 1,2
Fold 2 test: participant 3,4
Fold 3 test: participant 5,6
Fold 4 test: participant 7,8
```

각 fold에서 다음 참가자 pair를 validation으로 두고 나머지를 train으로 사용한다. 모든 모델에 동일한 fold를 적용하고 test fold는 epoch·threshold·hyperparameter 선택에 사용하지 않는다.

```text
Simple CSI-CNN × 4 folds
CSI-ResNet18   × 4 folds
EfficientNet-B0 × 4 folds
총 12회 학습
```

동일한 세 CNN을 UT-HAR와 CSI-HAR에도 각각 4-fold로 실행한다. 총 정식 학습은 `3개 데이터셋 × 3개 CNN × 4 folds = 36회`다. CSI-HAR는 fall이 없는 2분류임을 별도 표기한다. ESP-Fi 우승 CNN은 환경 4-fold leave-one-environment-out으로 추가 검증한다.

### 6.2 다른 데이터셋

- UT-HAR: 제공된 train/validation/test split 유지
- CSI-HAR: 방 단위 3-fold, walking/other_motion만 평가
- 자체 데이터: 참가자 분리와 공간 분리를 각각 수행하고 session/window 누수 금지

서로 다른 클래스 집합의 데이터셋 결과를 하나의 평균 정확도로 합치지 않는다.

### 6.3 모델 선택 지표

주 지표는 다음 순서로 본다.

1. fall recall: 실제 낙상을 놓치지 않는가
2. fall precision·시간당 거짓 경보: 과도한 경보가 없는가
3. macro-F1: 세 클래스가 균형 있게 분류되는가
4. walking F1과 confusion matrix
5. fold 평균, 표준편차와 참가자·공간별 최저 성능

최초 비교는 validation macro-F1로 checkpoint를 선택하되, 최종 모델은 fall recall 하한과 오탐 기준을 동시에 만족해야 한다. 우승 후보는 seed 3개 이상으로 반복한다.

## 7. CNN 학습 단계

### 7.1 단일 데이터 기준선

```text
ESP-Fi → Simple CSI-CNN / CSI-ResNet18 / EfficientNet-B0 4-fold
UT-HAR → 동일한 세 CNN stratified 4-fold
CSI-HAR → 동일한 세 CNN session-grouped 4-fold 2분류
```

모델, optimizer, epoch 상한, early stopping, augmentation과 seed를 가능한 한 동일하게 유지한다. 데이터 크기 때문에 변경이 필요하면 결과표에 명시한다.

### 7.2 다중 공개 데이터 사전학습

비교 대상은 다음과 같다.

1. ESP-Fi만 supervised pretraining
2. UT-HAR만 supervised pretraining
3. ESP-Fi+UT-HAR domain-balanced supervised pretraining
4. 모든 공개 CSI의 self-supervised pretraining 후 3분류 head 학습

다중 데이터 학습에서는 큰 데이터셋이 batch를 독점하지 않도록 dataset-balanced sampler를 사용한다. source dataset을 맞히는 shortcut을 줄이기 위해 instance normalization, subcarrier masking, packet dropout과 작은 amplitude/noise augmentation을 검증한다.

### 7.3 성능 향상 후보

- weighted cross entropy 기준선, focal loss 비교
- time shift, 작은 amplitude scaling과 Gaussian noise
- subcarrier masking과 packet dropout
- 제한적인 time crop·resampling
- hard-negative mining
- amplitude+차분 다채널 입력

낙상의 급격함과 지속시간을 훼손하는 강한 time warping은 사용하지 않는다. augmentation과 loss는 test를 보며 선택하지 않는다.

## 8. 자체 데이터 파인튜닝

공개 데이터 성능은 최종 성능이 아니다. 자체 ESP32-S3에서 다음 실험을 같은 locked test set으로 비교한다.

```text
A. 자체 데이터로 scratch 학습
B. ESP-Fi pretrained → 자체 데이터 fine-tuning
C. ESP-Fi+UT-HAR pretrained → 자체 데이터 fine-tuning
D. self-supervised public+own unlabeled → 자체 라벨 데이터 fine-tuning
```

파인튜닝 순서:

1. classifier head를 교체하고 backbone을 잠시 freeze
2. 낮은 learning rate로 전체 backbone unfreeze
3. validation macro-F1과 fall recall로 early stopping
4. 확정된 모델을 참가자·공간 locked test에서 한 번 평가
5. scratch 대비 개선이 반복될 때만 pretrained 모델 채택

자체 라벨이 적을 때는 라벨 데이터 비율 10%·25%·50%·100% 실험으로 사전학습이 라벨링 비용을 얼마나 줄이는지 측정한다.

## 9. Cross-domain과 WiTeacher 적용 시점

일반 supervised fine-tuning 기준선 이후에 Mean Teacher를 적용한다.

```text
Source: 라벨 있는 ESP-Fi/UT-HAR
Target: 라벨이 적거나 없는 자체 ESP32-S3 CSI
Student: augmentation된 target 학습
Teacher: Student 가중치의 EMA
Loss: source classification + target consistency + confidence pseudo-label
```

먼저 Mean Teacher만 구현하고 일반 fine-tuning과 비교한다. 효과가 확인된 뒤에만 WiTeacher의 StyleGAN 기반 source↔target 스타일 변환과 adaptive label smoothing을 추가한다. CSI-HAR의 fall 부재를 pseudo-label로 채운 것처럼 취급하지 않는다.

## 10. 실시간 ML 서버

학습 모델은 다음 구성으로 서버화한다.

```text
device별 ring buffer
  → moving 시 최근 950프레임 window
  → CNN batch inference
  → softmax/보정 확률
  → EMA 또는 연속 K회 안정화
  → fall_suspected / walking / other_motion / unknown
```

초기 추론 설정:

| 항목 | 후보 |
|---|---|
| window | 최근 950프레임 × 52 subcarrier |
| 호출 간격 | 33~100ms |
| 빈도 | 초당 10·20·30회 |
| 종료 유지 | moving 종료 후 1~3초 |

온라인 평가는 해당 시점까지 도착한 데이터만 사용한다. 미래 프레임을 포함한 오프라인 crop으로 실시간 성능을 부풀리지 않는다.

낮은 최대 확률, 높은 entropy, 학습 분포에서 먼 embedding은 `unknown`으로 거부한다. threshold와 연속 K값은 validation에서 정하고 temperature scaling 등으로 확률을 보정한다.

## 11. gateway와 전체 시스템 결합

현재 gateway는 serial의 `CSI_DATA`와 Radar 결과를 읽고 재실·moving을 계산한다. 통합은 기존 책임을 유지한 채 다음 단계로 진행한다.

### 11.1 데이터 계약

gateway가 ML 서버에 보내는 프레임 또는 50~100ms batch:

```json
{
  "deviceId": "rx-s3-001",
  "sessionId": "...",
  "sequence": 12345,
  "capturedAtUtc": "...",
  "channel": 6,
  "moving": true,
  "csiIq": [0, 1, -2, 3]
}
```

ML 서버 응답:

```json
{
  "deviceId": "rx-s3-001",
  "windowFinishedAtUtc": "...",
  "label": "fall_suspected",
  "scores": {"fall_suspected": 0.91, "walking": 0.03, "other_motion": 0.06},
  "confidence": 0.91,
  "modelVersion": "cnn-v001",
  "preprocessingVersion": "csi-window-v1"
}
```

실제 `CSI_DATA` 필드와 유효 I/Q 길이를 확정한 뒤 schema를 고정한다. MAC 필드는 보드 식별자로 가정하지 않고 gateway가 관리하는 `deviceId`를 사용한다.

### 11.2 통합 순서

1. 저장된 JSONL replay로 gateway→ML server 통신 테스트
2. 실시간 serial 한 대를 연결해 ring buffer와 결과 표시
3. moving=false일 때 추론 중지, 종료 후 tail 유지 검증
4. sequence 누락·중복·순서 변경·재연결 테스트
5. 여러 장치의 dynamic batching과 backpressure 적용
6. ML 서버 장애 시 gateway의 재실 기능은 유지하고 행동 상태를 unknown으로 표시
7. fall_suspected 이벤트에 원본 window·모델 버전·확률을 함께 저장

transport는 초기 구현에서 WebSocket 또는 gRPC streaming 중 하나를 선택한다. 프레임마다 동기 REST 호출하는 구조는 사용하지 않는다.

## 12. End-to-end 평가

분류 window 정확도만으로 전체 시스템을 평가하지 않는다.

- moving 탐지율 × CNN fall recall로 계산한 end-to-end 낙상 발견률
- 실제 행동 시작부터 첫 안정된 올바른 결과까지 지연
- 시간당·일일 fall_suspected 거짓 경보 수
- 연속 예측 label 전환 횟수
- packet loss·지연·재연결 후 복구 시간
- p50/p95/p99 전처리+추론 지연
- GPU 메모리, 초당 window 처리량과 동시 장치 수
- 장치당 서버 비용

정확도가 같으면 지연과 비용이 낮은 모델을 선택하되 작은 비용 차이 때문에 fall recall을 희생하지 않는다.

## 13. 버전 로드맵과 완료 기준

| 버전 | 핵심 작업 | 완료 기준 |
|---|---|---|
| v3 | 실제 moving 이벤트 경계 검증 | 행동 전·중·후와 gateway 경계 확인 |
| v3.1 | raw CSI sliding-window 파이프라인 | offline/replay/online window 일치 |
| v4 | 기존 고전 ML 비교 | 완료, v1.1을 일관되게 넘지 못함 |
| v5 | ESP-Fi CNN 구현·단일 split 기준선 | 세 CNN과 공통 checkpoint 파이프라인 준비 |
| v5.1 | 공개 데이터 CNN 교차검증 | 3개 데이터셋 × 3개 CNN × 4-fold 완료 |
| v5.2 | 환경·방 일반화와 multi-source pretraining | 단일 source 대비 전이 성능 비교 |
| v6 | 자체 데이터 수집·scratch 기준선 | 참가자·공간 locked test 확보 |
| v6.1 | 공개 사전학습 모델 fine-tuning | scratch 대비 반복 개선 |
| v7 | Mean Teacher/WiTeacher | 무라벨 target 사용 이득 확인 |
| v8 | CNN 실시간 inference server | replay와 serial 실시간 결과 일치 |
| v9 | gateway 통합 | 장애·재연결 포함 단일 장치 E2E 통과 |
| v10 | 다중 장치·운영 검증 | 지연·오탐·처리량 기준 충족 |

한 버전에서는 핵심 가설 하나만 검증하고 이전 최고 모델과 같은 프로토콜로 비교한다.

## 14. 모델 산출물과 재현

```text
ml/artifacts/cnn-v001/
├─ model.pt
├─ model.onnx
├─ preprocessing.json
├─ labels.json
├─ calibration.json
├─ split_manifest.json
├─ metrics.json
└─ manifest.json
```

다음을 반드시 기록한다.

- Git commit과 데이터 checksum/manifest
- 참가자·공간·세션 split
- window·stride·sampling rate·subcarrier
- 정규화·augmentation·loss
- 모델 구조·파라미터 수·seed·라이브러리 버전
- fold별 지표와 평균·표준편차
- threshold·확률 보정
- 서버 benchmark와 모델 파일 checksum

ONNX 변환 전후 출력 일치 회귀 테스트를 수행한다. 원본 CSI와 개인정보성 metadata는 모델 artifact에 포함하지 않는다.

## 15. 바로 수행할 작업

1. ESP-Fi, UT-HAR, CSI-HAR에서 세 CNN의 4-fold 학습 36회를 실행한다.
2. fold 평균·표준편차, 클래스별 recall과 confusion matrix를 `v5_1/RESULTS.md`에 기록한다.
3. ESP-Fi 우승 CNN을 환경 4-fold, CSI-HAR를 방 3-fold로 추가 검증한다.
4. 모델 중립 `ActivityModel.predict(window)` 계약과 950프레임 ring buffer를 gateway에 유지한다.
5. 학습된 ESP-Fi checkpoint를 monitor에 연결해 10·20·30Hz 추론 처리량을 측정한다.
6. 동시에 실제 행동 세션으로 v3 경계와 raw `CSI_DATA` 형식을 확정한다.
7. v3.1 sliding-window를 구현하고 자체 데이터 수집을 시작한다.
8. 자체 locked test를 만든 뒤 scratch와 공개 사전학습 fine-tuning을 비교한다.
9. 최고 CNN을 inference server로 패키징하고 JSONL replay부터 gateway 통합을 시작한다.

각 버전의 `RESULTS.md`에는 가설, 데이터와 split, 전처리, 모델·seed, fold별 지표, 평균·표준편차, confusion matrix, 실패 원인, 채택 여부와 다음 작업을 남긴다.
