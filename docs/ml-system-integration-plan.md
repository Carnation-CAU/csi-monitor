# ML 학습·시스템 적용 계획

최종 갱신일: 2026-08-16

## 목표와 역할 분리

학습은 GPU가 있는 데스크탑에서 수행하고, MacBook의 게이트웨이는 ESP32 CSI 수신,
공간 보정, 움직임 이벤트 분할, 기록과 앱 알림을 담당한다.

```text
ESP32 RX → MacBook gateway → raw CSI 시간창 → 데스크탑 ML 서버
                 ↑                              ↓
          이벤트·알림 기록 ← 안정화된 행동 확률
```

학습용 PC와 추론 위치는 별개다. 초기 통합에서는 데스크탑이 학습과 추론 서버를
겸하면 모델을 빠르게 교체할 수 있다. 모델이 확정된 뒤 ONNX로 내보내 MacBook에서
추론하거나 외부 서버로 옮길지는 지연, 운영비와 가용성을 측정해 결정한다.

## 동료 브랜치에서 이미 된 부분

`origin/feat/#2-motion-detection` 최신 커밋 `849ecdd`에는 다음이 있다.

- ESP-Fi HAR 공개 데이터 검사와 전처리
- 통계 특징 Logistic Regression 기준선
- 계층 분류, DTW, Random Forest, Gradient Boosting, SVM 비교
- 실제 gateway JSONL의 Radar moving 이벤트 분할기
- `fall / walking / other_motion` 2D CNN과 CSI-ResNet18 학습 환경
- 참가자·환경 분리 평가와 실험 결과 문서

현재 연구 결과에서 공개 데이터 기준 낙상 F1은 새 사람·새 환경에서 대략 50%이고,
DTW와 복잡한 고전 모델도 일관된 개선을 보이지 않았다. 이 모델은 구조 검증용이며
현재 앱 알림에 바로 연결하지 않는다. 직접 병합할 때는 이 브랜치가 앱 알림 변경
이전 기준에서 갈라졌으므로 `gateway/monitor.py`, `docs/usage.md` 충돌을 검토하고
ML 파일만 무조건 덮어쓰지 않는다.

## 단계별 진행 순서

### 1. 온라인 입력 계약 고정

게이트웨이는 raw `CSI_DATA`를 시각과 함께 ring buffer에 쌓는다. 공식 Radar가
`moving=true`가 되면 행동 시작 전 1.5초부터 종료 후 2초까지 보존하고, 1~4초
고정 길이 window를 250ms stride로 만든다. 학습 전처리와 온라인 전처리는 같은
파서와 window 생성 코드를 사용해야 한다.

첫 모델 서버 출력 계약은 다음처럼 고정한다.

```json
{
  "deviceId": "rx-s3-001",
  "windowFinishedAtUtc": "2026-08-16T12:00:00Z",
  "label": "fall_suspected",
  "scores": {
    "walking": 0.03,
    "fall_suspected": 0.91,
    "other_motion": 0.06
  },
  "confidence": 0.91,
  "modelVersion": "model-v001",
  "preprocessingVersion": "csi-window-v1"
}
```

낮은 최대 확률, 높은 entropy 또는 학습 분포에서 먼 입력은 `unknown`으로 거부한다.

### 2. 공개 데이터로 파이프라인 검증

데스크탑에서 동료 브랜치의 ESP-Fi HAR 파이프라인과 v5 CNN 기준선을 재현한다.
이 단계의 목적은 높은 숫자를 홍보하는 것이 아니라 데이터 로더, GPU 학습,
체크포인트, 참가자·환경 분리 평가와 모델 내보내기가 반복 가능한지 확인하는 것이다.

### 3. 자체 ESP32-S3 데이터 정렬

공개 데이터와 자체 보드는 장치, subcarrier, 표본률, 방과 배치가 다르다. 공개
모델을 그대로 적용한 정확도를 시스템 정확도로 보지 않는다. 자동 감지 이벤트와
raw CSI를 묶고, 실제 행동 구간만 사후 확인해 라벨링한다. 평상시 전체 시간을
수동 라벨링할 필요는 없지만 정확도 평가용 정답 라벨은 반드시 필요하다.

최소 라벨은 다음 세 그룹으로 시작한다.

- `walking`: 속도·방향이 다른 걷기
- `fall_suspected`: 매트리스 위 안전한 통제 모의 동작
- `other_motion`: 빠르게 앉기, 눕기, 일어나기, 물건 줍기, 몸 돌리기, 큰 팔 동작

실제 바닥 낙상은 수집하지 않는다. 한 사람·한 방의 sliding window가 train과
test에 섞이지 않도록 세션, 참가자와 공간 단위로 분리한다.

### 4. 기준선부터 비교

동일 split에서 Logistic Regression, tree 계열, 1D CNN/ResNet/TCN, 2D CNN을
차례로 비교한다. 복잡한 모델은 단순 기준선을 반복 실험에서 이길 때만 채택한다.
공개 데이터 사전학습 후 자체 데이터 fine-tuning과 처음부터 자체 데이터로 학습한
결과도 같은 test set에서 비교한다.

### 5. 정확도 대신 운영 지표로 선택

전체 accuracy 하나로 모델을 고르지 않는다.

- 클래스별 precision, recall, F1과 macro-F1
- 낙상 event recall과 PR-AUC
- 시간당·일일 거짓 낙상 알림 수
- 실제 행동 시작부터 감지까지의 p50/p95 지연
- 처음 보는 사람·공간별 평균과 최저 성능
- `unknown` 거부율과 확률 보정 후 Brier score/ECE

알림 임계값과 연속 K회 확정 규칙은 validation에서만 정하고 test 결과를 보고
다시 조정하지 않는다.

### 6. 모델 아티팩트로 전달

학습 결과는 체크포인트 하나가 아니라 아래 묶음으로 버전 관리한다.

```text
ml/artifacts/model-v001/
├─ model.onnx 또는 model.pt
├─ preprocessing.json
├─ labels.json
├─ thresholds.json
├─ manifest.json
└─ metrics.json
```

`manifest.json`에는 Git commit, 데이터셋·split, seed, 라이브러리 버전과 파일
체크섬을 기록한다. ONNX 변환 전후 출력 일치 회귀 테스트도 포함한다.

### 7. 게이트웨이에 단계적으로 적용

1. shadow mode: ML 결과를 기록만 하고 알림에는 사용하지 않는다.
2. 비교 mode: 현재 Radar 규칙과 ML 결과, 실제 확인 라벨을 나란히 저장한다.
3. 제한 알림: 높은 임계값과 시간 안정화를 통과한 낙상만 시험 앱에 전송한다.
4. 운영 후보: 여러 사람·공간에서 목표 recall과 오탐/시간 기준을 통과한 모델만
   raw CSI 추론 클라이언트를 통해 현재 `DetectionEvent` 기록·알림 경로에 연결한다.

현재 `LiveActionDetector`의 classifier 계약은 Radar 파생 특징 기준선을 비교하기
위한 선택적 인터페이스다. `T × 52` raw CSI 모델을 이 인터페이스에 억지로 넣지
않고, `CSI_DATA` ring buffer와 모델 서버 클라이언트를 별도 모듈로 둔다.

모델 서버가 끊기거나 응답이 늦으면 이전 예측을 계속 사용하지 않고 `unknown`으로
내린다. 이벤트 기록과 기본 Radar 상태 표시는 ML 서버와 무관하게 계속 동작한다.

## 바로 다음 작업

1. 동료 브랜치의 ML 커밋을 현재 앱 알림 변경 위로 안전하게 통합한다.
2. 실제 `CSI_DATA` I/Q 파서와 장치별 ring buffer를 gateway 공용 모듈로 만든다.
3. v3 이벤트 분할기를 오프라인과 온라인이 함께 쓰도록 이동한다.
4. MacBook→데스크탑 추론 API와 timeout·재시도·`unknown` 폴백을 구현한다.
5. 자동 이벤트별 raw CSI 파일과 사후 확인 라벨을 연결한다.
6. 데스크탑에서 공개 기준선을 재현한 뒤 자체 데이터 fine-tuning을 시작한다.
