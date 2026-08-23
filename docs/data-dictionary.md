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
| `label` | 예정 행동 또는 `unlabeled`; 최종 정답은 manifest의 `label` 사용 |
| `encoding` | 원문 디코딩 방식 |
| `raw` | ESP32 직렬 출력 원문 |

원문 parser가 추가되면 RSSI, noise floor, CSI 길이, I/Q 배열 등을 파생 필드로 저장한다. 원본 `raw`는 삭제하거나 덮어쓰지 않는다.

원본 경로는 `data/raw/<최종-행동-라벨>/<session-id>.jsonl`이다. 수집 종료 후
실제 행동이 확정되면 해당 행동 폴더로 이동하며, 기존의 평면 경로 원본도 계속
읽을 수 있다.

## 세션 manifest

운영체제, Python 버전, 포트, baud rate, 장치/방 식별자, 시작·종료 시각, 샘플 수, 원본 파일의 상대 경로를 기록한다. 특징 생성·예측·내보내기에서는 원본 각 줄의 임시 라벨보다 manifest의 최종 `label`을 정답으로 사용한다.

| 필드 | 의미 |
|---|---|
| `plannedLabel` | 수집 전에 선택한 예정 행동. 종료 후 선택 방식이면 `null` |
| `label` | 수집 종료 후 사용자가 확인한 실제 행동 또는 `unlabeled` |
| `labelConfirmedAtEnd` | 종료 후 실제 행동을 확정했는지 여부 |
| `labelCorrected` | 예정 행동과 실제 행동이 달라 수정되었는지 여부 |
| `valid` | 특징·학습·내보내기에 사용할 수 있는 세션인지 여부 |
| `invalidReason` | 무효 처리한 이유 |
| `channel` | 수집 시작 직전 live CSI에서 관측한 실제 채널 |
| `bandwidth` | live CSI의 `cwb`에서 판정한 실제 `HT20`/`HT40` |
| `configuredBandwidth` | Gateway와 공간 프로필이 요구하는 고정값 `HT20` |
| `radioObservation` | RX 응답 채널, CSI 채널, `cwb`, secondary channel, sig mode와 CSI 송신 주소의 수집 시작 스냅샷 |
| `radioIssuesDuringCollection` | 수집 도중 관측한 채널·대역폭 불일치 또는 CSI 중단 사유. 하나라도 있으면 세션은 자동 무효 |

행동 신호가 있는 수집은 `eventAtUtc`에 실제 신호 시각을 저장한다. 모의 낙상
수집은 `safetyProtocolConfirmed`에 GUI 사전 안전 확인 여부를 저장한다.
종료 라벨을 취소하거나 사전 안전 확인 없이 모의 낙상 라벨을 선택한 세션은
원본을 삭제하지 않고 `valid: false`로 보존한다.

## 공간 프로필

경로: `data/profiles/<profile-id>.json`

| 필드 | 의미 |
|---|---|
| `profileId` | 공간과 고정 배치를 식별하는 영문 ID |
| `displayName` | GUI에 표시하는 한글 이름 |
| `placement` | TX/RX 위치, 거리와 안테나 복원 지침 |
| `radio` | 채널과 TX 패킷 설정. 대역폭은 항상 `HT20`으로 강제 |
| `calibration` | 공식 빈 공간 보정에서 얻은 임계값과 설정 |
| `needsCalibration` | 현재 채널·배치에 새 보정이 필요한지 여부 |
| `devices` | 이 프로필에서 사용한 TX/RX MAC |
| `sessionIds` | 이 공간 프로필에 연결된 수집 세션 목록 |
| `referenceDatasets` | 행동 비교에 사용할 외부 팀 데이터셋 참조 목록 |

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
무효 세션, `unlabeled` 세션과 행동 라벨 형식이 아닌 링크 시험 세션은 제외한다. 모델
검증은 CSV 행을 다시 무작위로 쪼개지 않고 원본 세션 단위로 분리한다.

유효한 새 수집 세션에서 실험용 최근접 행동 예측이 가능하면 manifest의
`prototypePrediction`에 예측 라벨, 분리도, 거리, 비교 라벨 수와 실험용
표시를 기록한다. 분리도는 모델 확률이 아니며 행동당 한 기준 세션을 사용한
기능 시험 값이다.

## 공유 데이터셋 번들

내보내기 파일: `*.csi-dataset.zip`

| 경로 | 의미 |
|---|---|
| `dataset.json` | 출처 프로필, 라디오 설정, 라벨, 세션과 체크섬 |
| `raw/*.jsonl` | 수정하지 않은 원본 직렬 데이터 |
| `manifests/*.json` | 세션별 라벨과 수집 메타데이터 |

가져온 데이터 경로: `data/datasets/<dataset-id>`

공유 메타데이터의 `preprocessingVersion`은 어떤 상대 특징 규칙을 사용하는지
식별한다. 새 공간 프로필은 `referenceDatasets`에서 이 ID를 참조하며, 원본
세션의 `sourceProfileId`는 대상 프로필 ID로 덮어쓰지 않는다.

공간 간 참고 행동 비교에는 `wander/someone threshold`와
`jitter/move threshold` 상대 특징을 추가로 사용한다. 절대 특징도 CSV에는
남지만 현재 최근접 참고 예측은 상대 특징을 사용한다.

공간 전용 정지 재실 보조 판정은 현재 공간 프로필과 현재 빈방 보정 시각 이후에
수집한 유효한 로컬 `empty_room`, `standing_static`, `lying_static` 세션만
사용한다. 외부 참조 데이터셋과 이전 보정 시점의 세션은 보조 기준에서 제외한다.

## S3 raw CSI schema 2

새 수집 record는 기존 `raw`를 그대로 유지하면서 `recordType: "csi"`와 구조화된
`csi` object를 함께 저장한다. IQ가 원본이며 amplitude/phase는 재생 가능한 파생값이다.

| 필드 | 의미 |
|---|---|
| `csi.iqOrder` | ESP-IDF complex byte 순서 `imag-real` |
| `csi.iq` | subcarrier별 `[imaginary, real]`, HT20 LLTF에서 보통 `52×2` |
| `csi.amplitude`, `csi.phase` | IQ에서 계산한 파생 배열 |
| `csi.subcarrierIndex` | `-26..-1, 1..26`의 HT20 LLTF index |
| `csi.validSubcarrierMask` | pilot/null/first-word-invalid를 제외한 mask |
| `csi.deviceTimestampUs` | ESP 수신 timestamp, wrap을 고려해 time resampling에 사용 |
| `csi.rssi`, `csi.noiseFloor`, `csi.agcGain`, `csi.fftGain` | 수신/RF metadata |
| `csi.rate`, `csi.sigMode`, `csi.mcs`, `csi.channel`, `csi.bandwidth` | packet PHY 조건 |
| `csi.ltf` | 현재 `LLTF`; 다른 LTF가 섞이면 별도 session으로 분리 |

manifest schema 2는 `personId`, `positionId`, `activityId`, `deviceFamily`,
`csiTiming`을 추가한다. `csiTiming`에는 packet/s, mean/median/p95/max interval,
gap, missing sequence/loss, valid carrier 비율, RSSI/noise와 signal quality가 들어간다.
학습·locked test에는 `unknown` person/position metadata를 사용하지 않는다.

공간 profile의 `calibration.csiBaseline`에는 channel/bandwidth, subcarrier별 robust
center/scale, stable carrier mask, sample count와 calibration 시각을 저장한다.
channel 변경 시 이 baseline은 무효이며 약 300 stable frame 동안 자동 안정화한다.

## Event replay clip

경로: `data/events/clips/<event-id>.jsonl`

최종 낙상 의심 또는 분석 후보가 생기면 bounded ring buffer의 이전 5초와 이후
5초 raw record를 저장한다. clip에는 event ID/type, relative time, 원본 CSI와 당시
model/Radar/fusion evidence를 연결할 수 있는 timestamp가 포함된다. clip은 FN/FP
hard-negative mining 자료이며 원본 session을 대체하지 않는다.

## S3 학습 파생물

S3 모델 입력은 기본 100 Hz, `[-2초,+3초]`, stride 0.25초다. feature tensor axis는
`[feature, time, subcarrier]`이며 기본 feature는 room-relative amplitude,
temporal Δ, Δ², unwrap 후 relative phase delta다. event 주변의 잘못 정렬된 window는
negative로 강제 라벨링하지 않는다. 실험 JSON에는 dataset inventory, split group,
validation에서 선택한 threshold, window/event metrics, confusion matrix, PR/ROC curve,
FN/FP와 latency를 기록한다.
