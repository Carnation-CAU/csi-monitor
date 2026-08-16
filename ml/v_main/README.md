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
- 클래스: fall / walking / other_motion
- 외부 라벨: fall은 `fall_suspected`로 반환
- 모델 버전: `v5.1-efficientnet-b0-espfi-cv-fold1-20260816`
- 출처: `ml/v5_1/output/cross_validation/espfi/efficientnet_b0/fold-1/best.pt`

v5.1 4-fold 평균 test macro-F1이 가장 높은 ESP-Fi 모델을 선택했다. 개별
checkpoint는 test fold가 아니라 validation macro-F1이 가장 높은 fold 1을
사용했다. 이 checkpoint는 공개 데이터 기반 시스템 통합 후보이며, 자체
ESP32-S3 locked test를 통과한 최종 안전 모델은 아니다.

## Monitor에서 호출

저장소 루트에서 실행한다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-radar-monitor.ps1 `
  -Port COM7 `
  -ActivityModel ".\ml\v_main\model.pt" `
  -ActivityHz 20 `
  -ActivityWindowFrames 950
```

- `COM7`은 실제 ESP32 수신기 포트로 바꾼다.
- inference 빈도는 기본 20Hz이며 필요할 때 10~30Hz 범위에서 검증한다.
- gateway는 최근 950프레임이 쌓이고 `moving=true`일 때 background worker로
  모델을 호출한다.

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

```powershell
.\.venv\Scripts\python.exe -m unittest -v ml.v_main.test_v_main
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
