# 서버 기반 CSI 움직임 분류 개발 전략

최종 수정일: 2026-08-16

## 1. 목표와 확정된 역할

gateway가 재실과 움직임을 확인하면 ML 서버가 최근 수 초의 ESP32-S3 raw CSI로
`walking / fall_suspected / other_motion / unknown`을 분류한다.

```text
gateway
  채널·공간 보정 → 재실 판단 → moving 판단 → raw CSI와 시각 전달
                                                ↓
ML 서버
  ring buffer → 최근 N초 window → 반복 추론 → 시간축 안정화 → 행동 결과
```

gateway는 채널, 빈방 보정, `wander`·`jitter`, 재실과 `moving`을 담당한다. ML은
이를 재구현하지 않는다. ML의 주 입력은 `moving` 시각에 대응하는 raw CSI며 Radar
파생값은 품질 확인이나 보조 특징으로만 비교한다.

온디바이스 실행은 목표가 아니다. 서버에서 정확도, 낙상 recall, 거짓 경보율과
일반화 성능이 가장 좋은 모델을 선택한다. 모델 크기는 선제적으로 제한하지 않되
실시간 지연, 처리량과 장치당 서버 비용을 함께 기록한다.

## 2. 변경 범위와 책임

1. 행동 분류 코드·문서·실험 결과는 `ml/` 안에서 작업한다.
2. `gateway/`, `firmware/`, `scripts/`는 ML 실험에서 직접 수정하지 않는다.
3. gateway 변경이 필요하면 데이터 계약 변경안을 먼저 문서화한다.
4. `data/`의 원본, manifest와 공간 프로필은 읽기 전용으로 사용한다.
5. 학습과 실시간 추론은 같은 파서, subcarrier 선택, 정규화와 window 생성기를 쓴다.

## 3. 실시간 추론 구조

### 3.1 입력 버퍼

서버는 장치별 raw CSI ring buffer를 유지한다. `moving=true`가 되면 새 프레임이
들어올 때마다 또는 고정 stride마다 최근 N초 window를 모델에 넣는다.

| 항목 | 초기 후보 |
|---|---|
| window 길이 | 1초, 2초, 3초, 4초 |
| stride | 50ms, 100ms, 250ms |
| 추론 빈도 | 초당 4·10·20회 |
| 입력 | `T × 52` amplitude, 선택적으로 phase·Radar 보조 특징 |
| 종료 후 유지 | moving 종료 뒤 1~3초 |

낙상 후 정지를 관찰하도록 moving이 끝나도 짧은 시간 추론을 유지한다. 온라인
성능은 해당 시점까지 도착한 과거와 현재 데이터만으로 측정한다.

### 3.2 예측 안정화

window별 확률을 그대로 경보로 보내지 않고 validation에서 다음을 비교한다.

- 최근 K개 확률의 지수 이동평균
- 연속 K회 같은 클래스일 때 확정
- 낙상 확률 최고값과 지속시간 결합
- 전용 fall detector와 multiclass classifier 앙상블
- 낮은 최대 확률 또는 높은 entropy를 `unknown`으로 거부

경보 threshold와 K는 validation에서만 정한다.

### 3.3 출력 계약

```json
{
  "deviceId": "rx-s3-001",
  "windowFinishedAtUtc": "...",
  "label": "fall_suspected",
  "scores": {"walking": 0.03, "fall_suspected": 0.91, "other_motion": 0.06},
  "confidence": 0.91,
  "modelVersion": "model-v001",
  "preprocessingVersion": "csi-window-v1"
}
```

## 4. 데이터 파이프라인

### 4.1 raw CSI 표준화

```text
JSONL의 CSI_DATA
  → timestamp와 I/Q 파싱
  → 유효 subcarrier 선택
  → amplitude = sqrt(I² + Q²)
  → 이상 패킷·긴 공백 표시
  → 고정 표본률 재표본화 또는 마스크 생성
  → train 통계로 정규화
```

공개 ESP-Fi HAR와 자체 ESP32-S3가 모두 `time × subcarrier amplitude`가 되면 공개
데이터 사전학습과 자체 fine-tuning을 비교할 수 있다. 장치, 펌웨어, 방과 배치가
다르므로 공개 데이터 성능을 자체 환경 성능으로 해석하지 않는다.

정규화 후보:

- window별 z-score
- 세션 빈방 baseline 대비 변화량
- subcarrier별 train 평균·표준편차
- robust scaling(median/IQR)
- amplitude와 1차 차분의 다채널 입력

### 4.2 v3의 역할

v3는 모델이 아니라 오프라인 데이터 검증·생성 파이프라인이다.

- 실제 `moving` 구간과 행동 시각의 일치 확인
- 짧은 moving 단절 병합과 별도 행동 분리
- manifest 라벨 연결
- 동일 이벤트에서 CNN용 sliding window 생성
- raw CSI와 Radar timestamp 정렬 검증
- 세션·참가자·공간 단위 split 메타데이터 생성

현재 이벤트 전체 64시점 Radar 입력은 기존 산출물로 유지한다. 서버 모델의 주
입력은 이벤트 전체를 압축한 배열이 아니라 실시간과 동일한 고정 시간 window다.

### 4.3 window 라벨

한 세션의 모든 window에 세션 라벨을 무조건 붙이지 않는다.

- 실제 행동과 겹치는 window: manifest 행동 라벨
- 행동 전 준비 구간: 학습 제외 또는 context
- 행동 후 구간: 낙상 후 정지 분석용으로 별도 표시
- 경계가 불확실한 window: `unknown` 또는 학습 제외

`eventAtUtc`는 GUI 신호 시각이지 실제 동작 시작 정답이 아니다. v3 경계, 관찰
기록과 가능하면 동기화된 영상으로 실제 구간을 확인한다.

## 5. 데이터 구성 전략

### 5.1 공개 데이터

ESP-Fi HAR 4개 환경, 8명, 7행동, 2,240개를 다음에 사용한다.

- 공개 데이터 기준선 재현
- raw amplitude 모델 사전학습
- 모델 구조와 augmentation 후보 선별
- leave-one-participant/environment-out 평가

공개 `fall`과 자체 `fall_simulated_mattress`는 동일 행동이라고 단정하지 않는다.

### 5.2 자체 데이터

- `walking`: 느린·보통 걷기, 방향·속도 변화
- `fall_suspected`: 안전한 매트리스 위 통제된 모의 낙상
- `other_motion`: 빠르게 앉기, 눕기, 일어나기, 물건 줍기, 몸 돌리기,
  비틀거리기, 균형 회복, 큰 팔 동작

실제 바닥 낙상은 수집하지 않는다. 사람, 방, 위치, 방향, 날짜와 의복을 다르게
반복하며 클래스 표본 수보다 참가자·공간 다양성을 우선한다.

### 5.3 데이터 분할

1. 같은 세션과 이벤트에서 나온 window는 반드시 같은 split에 둔다.
2. 참가자 분리, 공간 분리와 시간 분리 평가를 각각 수행한다.
3. test 참가자·공간의 정규화 통계를 학습에 사용하지 않는다.
4. 모델·window·augmentation·threshold 선택은 validation에서만 한다.
5. 공개 데이터와 자체 데이터 결과를 별도로 기록한다.

## 6. 모델 후보군

모든 모델은 같은 split, window와 평가 코드에서 비교한다.

### 6.1 필수 기준선

- Logistic Regression
- Random Forest 또는 Gradient Boosting
- v1.1의 45개 통계 특징 모델

딥러닝 모델은 반드시 이 기준선을 반복 평가에서 넘어야 한다.

### 6.2 raw 시계열 모델

1. **InceptionTime 계열**: 여러 길이의 시간 패턴 동시 포착
2. **1D ResNet**: 강한 시계열 분류 기준선
3. **TCN**: dilated convolution으로 긴 문맥과 낮은 지연 결합
4. **CNN-LSTM/GRU**: 국소 변화와 장기 순서 결합
5. **Transformer encoder**: 긴 의존성과 subcarrier 관계 학습
6. **PatchTST 계열 encoder**: 긴 시계열을 patch 단위로 처리

1D CNN은 후보 중 하나일 뿐 최종 구조로 고정하지 않는다. 서버 GPU에서 큰 ResNet,
Transformer와 앙상블도 평가한다.

### 6.3 시공간·스펙트로그램 모델

raw amplitude, 차분, STFT/CWT를 `시간 × subcarrier` 또는 `시간 × 주파수`
다채널 이미지로 만들어 다음을 비교한다.

- 2D ResNet
- EfficientNet
- ConvNeXt
- Vision Transformer/Swin Transformer

스펙트로그램 전처리 비용도 추론 지연에 포함한다.

### 6.4 YOLO 사용 조건

YOLO는 단순 window 3분류의 첫 선택이 아니다. 다음 가설에서만 시험한다.

```text
긴 CSI spectrogram
→ 시간축 bounding box로 행동 발생 위치 탐지
→ box별 walking / fall_suspected / other_motion 분류
```

정확한 시작·종료 box 라벨이 있어야 한다. YOLO는 다음 기준선과 비교한다.

- gateway moving + window classifier
- 1D temporal detector
- spectrogram segmentation/detection 모델

event mAP뿐 아니라 낙상 recall, 시간당 오탐과 검출 지연에서 이겨야 채택한다.

### 6.5 사전학습과 자기지도학습

- ESP-Fi HAR supervised pretraining 후 자체 fine-tuning
- 자체 무라벨 CSI masked reconstruction
- contrastive learning(TS2Vec/CPC 계열)
- 공개·자체 데이터 domain adaptation

사전학습 모델과 scratch 모델은 같은 자체 test set에서 비교한다.

### 6.6 앙상블

단일 최고 모델 이후에만 시험한다.

- raw 1D 모델 + spectrogram 2D 모델 확률 평균
- 전용 binary fall detector + 3-class classifier
- 서로 다른 window 길이의 multi-scale ensemble
- fold별 모델 앙상블

참가자·공간 양쪽에서 개선되고 서버 비용 대비 이득이 있을 때 채택한다.

## 7. 학습 성능 최대화 전략

### 7.1 augmentation

- 시간 이동과 제한적인 crop
- amplitude scaling과 작은 Gaussian noise
- 일부 subcarrier masking
- packet dropout과 시간 gap simulation
- 제한적인 time stretching: 걷기 분기에만 비교
- mixup/cutmix: 라벨 경계 보존 여부 별도 검증

낙상의 급격함과 실제 지속시간을 훼손하는 강한 time warping은 사용하지 않는다.

### 7.2 불균형과 hard negative

- class-balanced sampler 또는 class weight
- focal loss와 weighted cross-entropy 비교
- 낙상 오인 생활 동작 hard-negative mining
- 참가자·공간별 최악 성능을 반영한 모델 선택
- 운영 오탐을 검토·라벨링해 다음 학습 세트에 추가

같은 낙상 세션의 거의 동일한 window를 과도하게 복제하지 않는다.

### 7.3 하이퍼파라미터 탐색

- window 길이와 stride
- 정규화 방식
- depth·width·kernel·patch 크기
- dropout, weight decay, learning rate
- loss와 class weight
- confidence와 시간 안정화 threshold

Optuna 등을 사용할 수 있지만 test set은 탐색에 사용하지 않는다. 최종 후보는 여러
seed로 반복한다.

### 7.4 확률 보정과 OOD

- temperature scaling 또는 isotonic calibration
- Expected Calibration Error와 Brier score
- energy, entropy 또는 embedding distance 기반 `unknown`
- 학습하지 않은 생활 행동을 OOD test로 평가

보정 전 softmax를 사용자 신뢰도로 표시하지 않는다.

## 8. 평가 지표

### 8.1 분류 성능

- 클래스별 precision, recall, F1
- Macro-F1, balanced accuracy와 confusion matrix
- `fall_suspected` PR-AUC
- 참가자별·공간별 평균과 최저 성능
- `unknown` 거부율과 거부 후 성능

### 8.2 실시간·이벤트 성능

- 실제 행동 시작부터 첫 올바른 예측까지 지연
- 낙상 event recall
- 시간당·일일 낙상 거짓 경보 수
- 연속 예측의 흔들림 횟수
- moving 탐지율 × 분류 recall로 계산한 end-to-end 낙상 발견률

중복 window가 지표를 부풀릴 수 있으므로 event 단위 결과를 주 지표로 둔다.

### 8.3 서버 운영 성능

- p50/p95/p99 전처리+추론 지연
- 장치 한 대당 초당 추론 횟수
- GPU/CPU 메모리와 동시 장치 수
- 장치당 월간 추론 비용 추정
- 패킷 지연·순서 변경·손실 시 복구 동작

정확도가 같으면 지연과 비용이 낮은 모델을 선택하되 작은 비용 차이로 낙상 성능을
희생하지 않는다.

## 9. 버전 로드맵

| 버전 | 핵심 가설 | 완료 기준 |
|---|---|---|
| v3 | 실제 moving 이벤트 경계를 신뢰할 수 있는가 | 실제 세션 경계·문맥 검증 |
| v3.1 | raw CSI와 Radar를 정렬하고 sliding window를 만들 수 있는가 | 오프라인·온라인 window 동일성 |
| v5 | 자체 데이터 고전 ML 기준선 | 참가자·공간 분리 기준 점수 |
| v6 | raw 시계열 딥러닝이 고전 ML을 넘는가 | InceptionTime/ResNet/TCN 반복 개선 |
| v7 | Transformer·사전학습이 일반화를 높이는가 | 새 참가자·공간에서 반복 개선 |
| v8 | spectrogram 2D 모델 또는 YOLO가 유효한가 | event 지표와 지연 모두 개선 |
| v9 | 앙상블·OOD·확률 보정 | 오탐 감소와 신뢰 가능한 confidence |
| v10 | 서버 실시간 통합 | 목표 동시 접속에서 end-to-end 기준 충족 |

한 버전에서는 핵심 가설 하나만 검증하고 이전 최고 모델과 같은 프로토콜로 비교한다.

## 10. 모델 저장과 재현

```text
ml/artifacts/model-v001/
├─ model.pt 또는 model.onnx
├─ preprocessing.json
├─ labels.json
├─ calibration.json
├─ manifest.json
└─ metrics.json
```

Git commit, 데이터 manifest와 split, window·stride·표본률·subcarrier, 정규화,
모델 구조와 파라미터, seed와 라이브러리, threshold, test 결과, 서버 benchmark와
파일 체크섬을 기록한다. ONNX/TorchScript 변환 전후 출력 일치도 회귀 테스트한다.

## 11. 완료된 연구와 현재 기준선

| 버전 | 결과 | 판단 |
|---|---|---|
| v0 | 최초 특징 모델, 낙상 F1 약 38% | 가능성 확인 |
| v0.1 | jump 등 큰 동작이 주요 낙상 오탐 | hard negative 필요 |
| v1 | 계층 분류·무활동도 일반화 부족 | 자체 데이터 우선 |
| v1.1 | 집중 Logistic, 사람 53.04%·환경 50.48% | 공개 기준선 |
| v2 | DTW가 일관되게 개선하지 못함 | 낙상 분기 미사용 |
| v3 | Radar 이벤트 전처리 합성 테스트 통과 | 실제 검증 진행 |
| v4 | RF·Boosting·SVM 모두 v1.1을 일관되게 넘지 못함 | 미채택 |

v1.1은 배포 모델이 아니라 공개 데이터 기준선이다. 최종 선택은 자체 참가자·공간
분리와 실시간 event 평가를 기준으로 한다.

## 12. 바로 할 일

1. 실제 행동 세션으로 v3 moving 이벤트 경계를 검증한다.
2. JSONL `CSI_DATA` 형식, 실제 표본률과 유효 52개 subcarrier를 확정한다.
3. v3.1에 timestamp 정렬, ring-buffer와 sliding-window 생성기를 구현한다.
4. 오프라인 JSONL window와 실시간 buffer window의 동일성을 테스트한다.
5. 자체 데이터를 참가자·공간·행동별로 확대한다.
6. v5 고전 ML 기준선을 만든다.
7. v6에서 InceptionTime, 1D ResNet과 TCN을 우선 비교한다.
8. 데이터가 충분해지면 Transformer, 2D 모델, YOLO와 앙상블로 확장한다.

## 13. 버전별 기록 규칙

각 `RESULTS.md`에는 가설과 변경점, 데이터와 split, window·전처리, 모델·seed,
클래스별 지표와 confusion matrix, event recall·오탐·지연, 참가자·공간 편차,
서버 지연·처리량·비용, 실패 원인, 채택 여부와 다음 가설을 남긴다.
