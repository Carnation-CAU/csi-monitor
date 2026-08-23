# v_main: 현재 시스템 행동 분류 모델

`v0`, `v1`, `v5_1` 같은 숫자 버전 폴더는 연구와 실험 이력을 보존한다.
실제 gateway가 참조할 현재 모델의 안정 경로는 이 폴더로 고정한다.

```text
ml/v_main/
├─ model.pt          현재 시스템용 PyTorch checkpoint (Git 제외)
├─ MODEL_SPEC.json   기계가 읽을 수 있는 모델·입출력 명세
├─ README.md         호출 방법, 응답 형식, 교체 절차
└─ test_v_main.py    checkpoint와 runtime 계약 확인
```

## 현재 모델

- 모델: EfficientNet-B0
- 학습 데이터: ESP-Fi HAR
- 입력: 최근 950프레임 × 52개 subcarrier amplitude
- 배포 무선 입력: ESP32-S3, HT20, LLTF, raw I/Q 길이 104
- 클래스: fall / walking / other_motion
- 외부 라벨: fall은 `fall_suspected`로 반환
- 모델 버전: `v5.1-efficientnet-b0-espfi-cv-fold1-20260816`
- 출처: `ml/v5_1/output/cross_validation/espfi/efficientnet_b0/fold-1/best.pt`

v5.1 4-fold 평균 test macro-F1이 가장 높은 ESP-Fi 모델을 선택했다. 개별
checkpoint는 test fold가 아니라 validation macro-F1이 가장 높은 fold 1을
사용했다. 이 checkpoint는 공개 데이터 기반 시스템 통합 후보이며, 자체
ESP32-S3 locked test를 통과한 최종 안전 모델은 아니다.

### raw CSI가 모델까지 가는 방식

모니터가 시리얼의 원본 `CSI_DATA` 문자열을 읽지만 그 문자열 전체가 PyTorch
모델의 입력은 아니다.

```text
CSI_DATA 문자열
→ 104개 raw I/Q 정수 파싱
→ 52개 (I,Q) 쌍
→ sqrt(I² + Q²) amplitude 52개
→ 최근 950프레임 적재
→ subcarrier별 window z-score
→ float32[1, 1, 950, 52]
→ model.pt
```

따라서 현재 모델은 phase, RSSI, noise floor, timestamp와 그 밖의 CSI metadata를
사용하지 않는다. 원본 문자열은 수집 JSONL에 그대로 보존되고 모델에는 amplitude만
전달된다.

현재 parser는 104개 값을 ESP-IDF 순서인 imaginary/real complex pair로 보존하고
52개 amplitude·phase를 파생한다. 현재 C3 checkpoint에는 호환성을 위해 amplitude만
전달하지만 S3 학습 pipeline은 IQ에서 상대 amplitude, Δ/Δ²와 phase variation을 다시 만든다.
HT20 LLTF 입력 shape를 맞추는 것은 configuration mismatch만 줄일 뿐,
이것만으로 정확도 향상을 보장하지는 않는다. 모델 학습 데이터는 ESP32-C3 기반이고
실제 입력은 ESP32-S3이며 공간·배치·안테나·채널 차이도 남아 있으므로, 같은 HT20
설정의 자체 S3 데이터로 locked test를 해야 실제 정확도를 판단할 수 있다.

## Monitor에서 호출

저장소 루트에서 실행한다.

Windows:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-radar-monitor.ps1 `
  -Port COM7
```

macOS:

```bash
./scripts/start-radar-monitor.sh /dev/cu.wchusbserial-RECEIVER
```

- `COM7`은 실제 ESP32 수신기 포트로 바꾼다.
- 두 실행 스크립트 모두 기본 `ml/v_main/model.pt`를 사용한다.
- inference 빈도는 기본 5Hz이며 실제 latency와 연속 오탐을 측정해 조정한다.
- gateway는 최근 950프레임이 쌓이면 Radar `moving`과 무관하게 background worker로
  연속 추론한다. `moving`과 tail은 진단 호환 정보일 뿐 ML hard gate가 아니다.
- checkpoint의 입력 크기를 직접 읽으므로 실행 인자로 950을 다시 지정하지 않는다.
- 모델이 정상 로드되면 gateway가 RX에 LLTF decimal 원시 CSI 출력을 자동으로
  요청한다. 펌웨어 명령 인자의 철자만 `LLFT`다. 공식 GUI에서 raw display를
  별도로 켜지 않는다.

모델 로드 시 `MODEL_SPEC.json`의 SHA-256, 입력 크기, 라벨, architecture와 모델
버전을 검증한다. Windows NVIDIA에서는 CUDA, Apple Silicon에서는 MPS, 그 밖의
환경에서는 CPU를 선택하며 MPS 연산이 실패하면 CPU로 폴백한다.

## 낙상 후보와 알림

겹치는 950프레임 window의 raw `fall_suspected` score 0.10 이상을 2초 episode로
묶는다. Radar fall, CSI motion/impact와 post-event score는 15초 구간의 event
proposal이다. `recall_first_soft_fusion_v3`는 이 score를 결합해 0.72 이상이면 최종
낙상 의심을 만든다. 아직 미보정 C3 모델이므로 raw ML 0.85 이상이어도 CSI 또는
Radar event proposal 한 개는 필요하지만, Radar 자체나 낙상 후 정지는 필수가 아니다.
CSI motion/impact/post-event를 0.30/0.45/0.25로 묶은 제안과 Radar fall/motion 제안 중
가장 강한 사건 근거를 사용하므로 선택적인 약한 센서가 강한 근거를 희석하지 않는다.
기준선 준비 또는 채널 변경 직후 3초 안에 시작한 CSI proposal은 startup transient로
격리한다.
한 CSI proposal은 한 번만 사용하고 연속 최종 판정은 30초 동안 같은 사건으로 병합한다.

0.10/0.72/0.85는 두 S3 낙상 FN을 분석해 만든 개발 통합값이며 안전 확률이 아니다.
동일 로컬 replay에서는 기존 0/2에서 2/2로 복구했지만, 낙상 2건과 빈 방 1건뿐이라
일반 성능으로 보고할 수 없다. 새 S3 grouped validation의 PR curve로 재선택해야 한다.
상세 근거와 명령은 `docs/s3-recall-first-architecture.md`에 기록한다.

## Python에서 직접 호출

저장소 공용 `.venv`를 사용한다.

```python
from dataclasses import asdict
from pathlib import Path

import numpy as np

from csi_gateway.activity import ActivityWindow
from ml.runtime import TorchCnnActivityModel

model = TorchCnnActivityModel(Path("ml/v_main/model.pt"))
amplitude = np.asarray(csi_amplitude, dtype=np.float32)  # shape: (950, 52)
window = ActivityWindow(
    amplitude=amplitude,
    first_sequence=1001,
    last_sequence=1950,
    finished_at="2026-08-16T20:30:00+09:00",
)
prediction = model.predict(window)
print(asdict(prediction))
```

`amplitude`는 반드시 시간 순서의 `float32[950, 52]`여야 한다. runtime이 window
안에서 subcarrier별 z-score를 적용하므로 호출자가 다시 정규화하지 않는다.

## 응답 형식

`ActivityModel.predict(ActivityWindow) -> ActivityPrediction` 계약을 사용한다.

```json
{
  "label": "fall_suspected",
  "scores": {
    "fall_suspected": 0.91,
    "walking": 0.03,
    "other_motion": 0.06
  },
  "confidence": 0.91,
  "first_sequence": 1001,
  "last_sequence": 1950,
  "window_finished_at": "2026-08-16T20:30:00+09:00",
  "model_version": "v5.1-efficientnet-b0-espfi-cv-fold1-20260816",
  "preprocessing_version": "amplitude-zscore-v1"
}
```

| 필드 | 형식 | 의미 |
|---|---|---|
| `label` | string | 최고 확률 외부 라벨 |
| `scores` | string→float | 세 클래스 softmax 확률 |
| `confidence` | float | 선택된 라벨의 확률 |
| `first_sequence` | integer | 판단 window 첫 CSI sequence |
| `last_sequence` | integer | 판단 window 마지막 CSI sequence |
| `window_finished_at` | string | 마지막 프레임 수집 시각 |
| `model_version` | string | 배포 모델 식별자 |
| `preprocessing_version` | string | runtime 전처리 계약 버전 |

## 모델 확인

Windows와 macOS에서 동일한 명령으로 실제 배포 runtime을 점검한다.

```powershell
csi-gateway activity-model-check --project-root .
```

```bash
csi-gateway activity-model-check --project-root .
```

이 명령은 SHA-256과 계약을 검증한 후 실제 checkpoint로 1회 추론하고 사용 장치,
입력 크기, latency를 JSON으로 출력한다. `syntheticPrediction`은 인공 입력에 대한
호환성 점검 결과이며 모델 정확도나 실제 행동 판정으로 해석하지 않는다.

checkpoint 계약 단위 테스트는 다음과 같다.

```powershell
.\.venv\Scripts\python.exe -m unittest -v ml.v_main.test_v_main
```

```bash
.venv/bin/python -m unittest -v ml.v_main.test_v_main
```

모델 파일 존재, 메타데이터, `950 x 52` 입력 추론, 확률 합과 응답 버전을
확인한다.

## 모델 교체 규칙

1. 숫자 버전 폴더에서 고정 protocol로 연구·평가한다.
2. fold 완전성, NaN, locked test, latency와 오경보를 확인한다.
3. 승인한 checkpoint를 `ml/v_main/model.pt`로 복사한다.
4. checkpoint의 `model_version`과 `MODEL_SPEC.json`의 출처·성능을 갱신한다.
5. `test_v_main.py`와 gateway 전체 테스트를 다시 실행한다.

`model.pt`는 checkpoint이므로 Git에 추가하지 않는다. `README.md`,
`MODEL_SPEC.json`, 검증 코드는 Git으로 관리한다.
