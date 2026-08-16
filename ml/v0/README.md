# v0 — 데이터 형식 점검

v0의 첫 목표는 모델 학습이 아니라 실제 입력 데이터의 형태와 품질을 확인하는
것이다. 기존 코드를 import하거나 수정하지 않고 독립적으로 실행한다.

## 현재 상태

2026-08-11 기준 자체 `data/raw/`에는 실제 세션 파일이 없지만, 공개
ESP-Fi HAR 저장소에서 바로 사용할 수 있는 처리본을 다음 위치에 내려받았다.

```text
ml/dataset/raw/ESP-Fi-HAR/Model Code/Data/
```

실제 검사 결과:

- `.mat` 560개: train 490개, test 70개
- 7개 행동별 80개: `arm_wave`, `fall`, `jump`, `run`, `squat`, `turn`, `walk`
- 참가자 8명, 행동별 10회
- 모든 파일에 `CSIamp` key
- 모든 배열 shape `950 x 52`, dtype `float64`
- 파일명의 scenario ID는 모두 `3`: 공개 저장소의 benchmark 처리본은 한 환경분

저장소의 전체 4개 환경 원본은 별도 대형 RAR로 제공된다. v0는 먼저 checkout된
한 환경 처리본 560개로 전처리와 분류 기준선을 검증한다. 대형 원본 전체를 받기
전에 이 작은 범위에서 파이프라인을 확인한다.

검사 도구는 다음 입력을 지원한다.

- 프로젝트 JSONL: `CSI_DATA`와 `RADAR_DADA` 포함 여부 및 기본 통계
- 공개 데이터 `.mat`: numeric array의 key, shape, dtype과 값 범위

## 실행

프로젝트 수집 데이터:

```powershell
.\.venv\Scripts\python.exe ml\v0\inspect_data.py --input data\raw
```

다운로드한 공개 데이터:

```powershell
.\.venv\Scripts\python.exe ml\v0\inspect_data.py `
  --input "ml\dataset\raw\ESP-Fi-HAR\Model Code\Data"
```

결과는 기본적으로 `ml/v0/output/`에 생성된다.

```text
summary.json   전체 파일과 표본 요약
files.csv      파일별 형식·shape·표본 수
```

## 다음 작은 작업

1. `CSIamp[950, 52]`의 시간축과 정규화 방식을 확인한다.
2. amplitude에서 motion-energy 시계열을 만든다.
3. 행동별 대표 파형과 단순 규칙 기준선을 비교한다.
4. 기존 train/test가 아닌 참가자 단위 split을 새로 고정한다.

