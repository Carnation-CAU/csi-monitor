# v3 ESP32-S3 추론 입력 전처리

gateway가 저장한 JSONL을 읽어 `moving` 이벤트 단위의 ML 입력으로 변환한다.
gateway 코드는 수정하거나 import하지 않으며 모든 구현은 `ml/v3/`에 독립돼 있다.

## 처리 흐름

```text
gateway JSONL + session manifest
  → RADAR_DADA 및 링크 로그 파싱
  → 짧게 끊긴 moving 구간 병합
  → 앞 1.5초·뒤 2.0초 문맥 추가
  → 64개 시간점의 고정 길이 신호
  → 이벤트 특징 CSV와 추론 입력 JSONL
```

한 번만 발생한 `moving=true`는 기본적으로 잡음 후보로 제외한다. 모든 분할 값은
CLI 인자로 바꿀 수 있으며, 실제 수집 데이터 검증 후 고정해야 한다.

## 실행

프로젝트 루트에서 실행한다.

```powershell
ml\.venv\Scripts\python.exe ml\v3\prepare_events.py
```

설정 변경 예시:

```powershell
ml\.venv\Scripts\python.exe ml\v3\prepare_events.py `
  --max-moving-gap 1.0 `
  --pre-context 1.5 `
  --post-context 2.0 `
  --min-moving-samples 2 `
  --fixed-length 64
```

`data/manifests/*.json` 중 `valid: true`이고 실제 라벨이 확정됐으며 원본 파일이
존재하는 세션만 자동으로 처리한다.

## 출력

기본 출력 위치는 `ml/v3/output/`이며 Git에서 제외된다.

| 파일 | 내용 |
|---|---|
| `events.jsonl` | 이벤트별 메타데이터, 특징, 64길이 시계열을 담은 추론 입력 |
| `features.csv` | 전통적인 머신러닝 학습·비교에 사용하는 이벤트별 특징 한 행 |
| `summary.json` | 세션·이벤트 수와 파싱 오류 등 데이터 품질 정보 |

### 고정 길이 입력 채널

- `wander_relative`: `wander / someone_threshold`
- `jitter_relative`: `jitter / move_threshold`
- `moving`
- `someone`
- `rssi`

각 채널은 이벤트 앞뒤 문맥을 포함해 64개 시간점으로 선형 보간한다. threshold가
0인 표본의 상대값은 0으로 처리한다. RSSI가 일부 누락되면 주변 관측값으로
보간하고, 전체가 없으면 0과 `rssi_available_ratio=0`으로 기록한다.

### 레이블 변환

| gateway 라벨 | ML 목표 라벨 |
|---|---|
| `walking_slow` | `walking` |
| `fall_simulated_mattress` | `fall_suspected` |
| 나머지 유효 수집 행동 | `other_motion` |
| 미확정 라벨 | `unknown` |

빠르게 앉기, 눕기, 일어나기, 물건 줍기 등은 낙상 오탐을 줄이기 위한
`other_motion` hard negative로 유지한다.

## 학습과 추론에서 함께 사용

저장된 학습 세션에는 `prepare_session()`을 사용하고, 추론에서는 일정 시간 동안
모은 `RadarPoint` 버퍼에 `segment_moving_events()`와 `make_event_record()`를
동일하게 적용한다. 실제 gateway 연결부는 모델을 확정한 뒤 추가한다.

이 방식은 학습 시 전처리와 실제 추론 시 전처리가 달라지는 것을 방지한다.

## 현재 한계

- 현재 변환기는 `RADAR_DADA`와 링크 RSSI/패킷률을 사용하며 `CSI_DATA` I/Q
  배열은 아직 입력으로 만들지 않는다.
- 로컬 `data/raw/`와 `data/manifests/`에 실제 수집 세션이 없어 실제 이벤트
  경계 검증은 아직 수행하지 못했다.
- 분할 기본값은 초기값일 뿐이며 실제 걷기·생활 동작 세션을 보고 조정해야 한다.
- `moving` 단계에서 놓친 행동은 분류 모델까지 도달하지 않는다.

## 테스트

```powershell
ml\.venv\Scripts\python.exe -m unittest ml\v3\test_prepare_events.py
```

