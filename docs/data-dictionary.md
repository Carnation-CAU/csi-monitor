# 데이터 사전

## 원본 JSON Lines

한 줄이 하나의 직렬 프레임이다.

| 필드 | 의미 |
|---|---|
| `schemaVersion` | 데이터 스키마 버전 |
| `sessionId` | 수집 세션 식별자 |
| `sampleId` | 세션 내 1부터 시작하는 순번 |
| `timestampUtc` | UTC ISO 8601 수신 시각 |
| `deviceId` | CSI 수신기 식별자 |
| `label` | 실험 행동 라벨 |
| `encoding` | 원문 디코딩 방식 |
| `raw` | ESP32 직렬 출력 원문 |

원문 parser가 추가되면 RSSI, noise floor, CSI 길이, I/Q 배열 등을 파생 필드로 저장한다. 원본 `raw`는 삭제하거나 덮어쓰지 않는다.

## 세션 manifest

운영체제, Python 버전, 포트, baud rate, 장치/방 식별자, 시작·종료 시각, 샘플 수, 원본 파일의 상대 경로를 기록한다.

행동 신호가 있는 수집은 `eventAtUtc`에 실제 신호 시각을 저장한다. 모의 낙상
수집은 `safetyProtocolConfirmed`에 GUI 안전 확인 여부를 저장한다.

## 공간 프로필

경로: `data/profiles/<profile-id>.json`

| 필드 | 의미 |
|---|---|
| `profileId` | 공간과 고정 배치를 식별하는 영문 ID |
| `displayName` | GUI에 표시하는 한글 이름 |
| `placement` | TX/RX 위치, 거리와 안테나 복원 지침 |
| `radio` | 채널, 대역폭과 TX 패킷 설정 |
| `calibration` | 공식 빈 공간 보정에서 얻은 임계값과 설정 |
| `needsCalibration` | 현재 채널·배치에 새 보정이 필요한지 여부 |
| `devices` | 이 프로필에서 사용한 TX/RX MAC |
| `sessionIds` | 이 공간 프로필에 연결된 수집 세션 목록 |

채널 자동 비교로 선택 채널이 바뀌면 기존 보정값은 무효 처리되고
`needsCalibration`이 `true`가 된다. 빈 공간 보정이 끝나야 새 임계값이
저장된다.

각 공간은 `data/profiles` 아래의 독립 JSON 파일로 저장된다. GUI에서 현재
선택한 프로필의 채널 비교·보정·행동 수집 결과만 해당 파일에 갱신된다.
GUI에서 삭제한 프로필은 `data/profiles/archive`로 이동하며 원본 수집 데이터는
삭제하지 않는다.

## 행동 인식용 특징 CSV

경로: `data/processed/<profile-id>-features.csv`

한 행이 하나의 유효한 행동 수집 세션이다. `wander`, `jitter`, 움직임·사람
판정 비율, 전반부·후반부 jitter, RSSI와 패킷률의 요약 특징을 저장한다.
무효 세션과 GUI 행동 라벨 목록에 없는 링크 시험 세션은 제외한다. 모델
검증은 CSV 행을 다시 무작위로 쪼개지 않고 원본 세션 단위로 분리한다.

유효한 새 수집 세션에서 실험용 최근접 행동 예측이 가능하면 manifest의
`prototypePrediction`에 예측 라벨, 분리도, 거리, 비교 라벨 수와 실험용
표시를 기록한다. 분리도는 모델 확률이 아니며 행동당 한 기준 세션을 사용한
기능 시험 값이다.
