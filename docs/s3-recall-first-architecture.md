# ESP32-S3 Recall-first 낙상 감지 재설계

이 문서는 2026-08-24 코드·로컬 원시 데이터 기준 분석, 구현 결정, 재생 비교와 다음 검증 조건을 기록한다. 가장 중요한 KPI는 Fall Recall이며, 로컬 데이터가 적기 때문에 재생 결과와 일반화 성능을 구분한다.

## 수정 전 분석

### 1. 현재 CSI 수집 구조

`csi_send` ESP32-S3가 ESP-NOW broadcast를 약 100 Hz로 송신하고, `console_test` ESP32-S3가 STA/promiscuous 모드에서 CSI callback으로 수신한다. PC Gateway는 2 Mbps UART에서 `CSI_DATA`와 `RADAR_DADA`를 읽는다. callback 쪽 무거운 ML 연산은 없고 PC background worker가 모델을 실행한다.

### 2. 현재 ESP32-S3 Wi-Fi 설정

- 채널 후보: 1/6/11, 기본 6, 설치 보정 후 고정
- 대역폭: HT20, secondary channel 없음
- LTF/CSI: 현재 원시 길이 104의 LLTF, 52 complex bins
- 전력 절약: RX power save 비활성
- 공식 ESP-IDF CSI byte 순서는 complex pair의 imaginary, real이다. LLTF/HT-LTF/STBC-HT-LTF 순서와 실제 길이는 packet 설정에 따라 달라지므로 metadata와 `len`을 함께 보존한다.

참고: [Espressif esp-csi](https://github.com/espressif/esp-csi), [ESP-IDF Wi-Fi CSI 문서](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32/api-guides/wifi.html).

### 3. 현재 CSI sampling rate

유효 S3 세션에서 CSI는 약 97.7~99.6 Hz, device timestamp 간격 median 약 10 ms, p95 약 12 ms였다. 최대 gap은 약 22.8~44.2 ms였고 host UART 수신 간격 p95는 일부 세션에서 약 19.5 ms, 최대 약 50 ms였다. 따라서 nominal 100 Hz 자체보다 불규칙 시간축을 frame index로 취급한 문제가 더 컸다.

### 4. 현재 preprocessing

수정 전 배포 모델은 104 raw IQ를 52 amplitude로 바꾼 뒤 최근 950 frame을 subcarrier별 window z-score하고 EfficientNet에 넣었다. phase, RSSI, noise floor, AGC, packet gap, baseline은 모델 입력과 최종 판정에 사용하지 않았다. timestamp resampling, pilot/invalid mask, adaptive room baseline도 없었다.

### 5. 현재 RADAR 알고리즘

`RADAR_DADA`의 `moving`, jitter/move threshold와 보정값을 사용했다. 충격 후보 후 8초 동안 post-moving ratio가 0.2 이하일 때 Radar 낙상 후보를 만들었다. 빠르게 회복하거나 Radar movement가 약한 낙상은 이 단계에서 사라질 수 있었다.

### 6. 현재 ML 모델

EfficientNet-B0, 입력 `950×52` amplitude, 출력 `fall/walking/other_motion` softmax다. 학습 원천은 ESP-Fi ESP32-C3이며 공개 교차검증 평균 Fall Recall은 약 86.9%였지만, ESP32-S3 locked test나 score calibration은 없었다. 로컬 S3 두 낙상의 최대 raw score는 각각 0.1411과 0.3124로 기존 0.8 기준보다 훨씬 낮았다.

### 7. 현재 최종 Fall 판정 조건

수정 전에는 Radar `moving`일 때와 3초 tail에서만 ML을 실행했다. 이어서 ML score 0.8 이상 episode와 Radar의 `impact → 8초 무회복` 낙상 사건이 15초 안에 모두 있어야 최종 알림을 보냈다. 즉 사실상 `Radar gate AND ML threshold AND Radar fall/stillness` 구조였다. 로컬 S3 낙상 2건 모두 Radar fall event 0건, ML 0.8 미만이어서 동일 재생 Recall은 0/2였다.

### 8. 순간 움직임을 놓친 원인

주원인은 nominal packet rate 부족이 아니라 다음 결합이었다.

1. Radar movement가 ML 실행 자체를 막음
2. 최종 boolean AND가 Radar miss를 그대로 Fall FN으로 바꿈
3. C3 모델의 S3 domain shift와 미보정 softmax
4. 9.5초 model window와 8초 무회복 확인에 따른 긴 지연
5. 불규칙 packet 간격을 고정 frame 간격처럼 사용

### 9. C3 → S3 domain shift

52-bin shape와 HT20이 같아도 RF front-end, AGC, noise, scale, packet timing, 방·배치 분포는 같지 않다. 실제 로컬 점수가 이 차이를 보여준다. 기존 C3 checkpoint는 새 S3 모델이 확보될 때까지 보조 evidence로만 유지하며, 최종 모델 선택 데이터는 S3 실측 IQ로 제한한다.

### 10. bottleneck TOP 5

1. Radar hard gate와 final AND
2. 유효 S3 낙상 IQ 2건뿐인 데이터 부족
3. Raw IQ/phase/metadata를 학습 pipeline에서 활용하지 않음
4. room/channel baseline과 timestamp resampling 부재
5. event-level FN replay, latency, PR/ROC, grouped locked test 부재

### 11. 유지한 코드

- 고정 100 Hz TX stream과 S3 RX raw CSI 출력
- HT20/LLTF 104-byte 계약
- 원문 JSONL 보존, session manifest, 공간 profile
- background ML worker, Radar/presence 진단, alert contract
- 현재 C3 checkpoint adapter와 SHA-256 계약

### 12. 제거한 동작

- Radar `moving`을 ML 실행의 필수 조건으로 사용
- Radar fall과 ML fall의 boolean AND를 최종 알림의 필수 조건으로 사용
- post-fall stillness를 hard requirement로 사용
- 낮은 signal quality를 drop gate로 사용하는 설계

### 13. 수정한 코드

- CSI parser: IQ 순서, phase, 전체 metadata, carrier index/mask 보존
- activity engine: device timestamp 기반 100 Hz resampling, 연속 추론
- calibration/profile: robust subcarrier baseline, movement-safe EMA, channel 변경 무효화/자동 안정화
- event aggregator: high-recall candidate, 15초 evidence history, score soft fusion
- monitor/GUI: packet timing, signal quality, state와 fusion 근거 표시

### 14. 새로 만든 코드

- `csi_pipeline.py`: timing/quality, adaptive baseline, phase 처리, state detector
- `event_clips.py`: 후보 주변 -5/+5초 raw clip
- `ml/s3/dataset.py`: S3 IQ resampling, relative amplitude, Δ/Δ²/phase-delta, overlap window, augmentation
- `ml/s3/features.py`, `models.py`, `training.py`: XGBoost/TCN/CNN+GRU/2D CNN 실험
- `ml/s3/evaluation.py`: window/event metrics, latency, PR/ROC, threshold curve, grouped split
- `ml/s3/replay_compare.py`: 같은 세션의 기존/개선 runtime 재생

### 15. 추천 최종 Architecture

```text
S3 TX constant traffic
  → S3 RX raw IQ + timestamp + RF metadata
  → bounded serial/ring buffer
  → timestamp resampling + carrier mask
  → robust room baseline + relative amplitude/phase change
  ├→ high-recall signal event proposal
  ├→ continuous temporal S3 classifier
  └→ Radar proposal
  → score fusion (no Radar/stillness veto)
  → event episode/state decision
  → alert + -5/+5초 replay clip
```

## 구현된 실시간 판정

상태는 `IDLE → MOVEMENT → HIGH_ENERGY_EVENT → POST_EVENT_MONITORING`을 기록한다. 현재 S3 전용 학습 데이터가 부족하므로 배포 checkpoint는 아직 C3 모델이다. raw ML 0.10부터 episode를 보존하고, raw C3 score를 S3 개발 replay용 evidence strength로 변환한 뒤 motion/impact/post-event/Radar proposal과 결합한다. CSI의 motion 0.30, impact 0.45, post-event 0.25를 하나의 CSI proposal로 만들고, 같은 15초 구간의 Radar fall/motion proposal과 비교해 가장 강한 사건 근거를 사용한다. 따라서 선택적인 약한 센서가 강한 사건 근거를 희석하지 않는다. 기준선 준비 또는 채널 변경 직후 3초 안에 시작한 CSI proposal은 startup transient로 격리한다. 미보정 C3 모델은 raw ML 0.85 이상이어도 CSI 또는 Radar event proposal이 있어야 하며 Radar 자체나 낙상 후 정지는 필수가 아니다. fusion score 0.72 이상에서 최종 낙상 의심을 만들고, 한 CSI proposal은 한 번만 사용하며 30초 안의 반복 판정은 같은 물리 사건으로 병합한다.

이 수치는 안전 인증된 확률이 아니다. 새 S3 grouped validation이 확보되면 PR curve에서 목표 Recall을 만족하는 threshold로 반드시 다시 선택한다.

신호 품질은 packet rate/gap/loss, valid carrier, RSSI/noise를 합쳐 표시하지만 낙상을 삭제하지 않는다. 채널이 바뀌면 기존 baseline을 즉시 무효화하고 약 300 stable frame의 자동 안정화 후 다시 적응한다. baseline EMA는 no-motion confidence 0.90 이상이며 fall candidate가 아닐 때만 갱신한다.

## 동일 데이터 전후 비교

명령:

```bash
PYTHONPATH=gateway/src:. .venv/bin/python -m ml.s3.replay_compare
```

평가 데이터는 raw IQ가 실제로 존재하는 유효 S3 낙상 2세션과 빈 방 1세션뿐이다. event tolerance는 cue -2초/+15초이며 한 물리 낙상당 최대 한 탐지만 TP로 매칭했다.

| 지표 | 수정 전 | 수정 후 |
|---|---:|---:|
| Fall Recall | 0/2 = 0% | 2/2 = 100% |
| Fall Precision | 0% | 2/2 = 100% |
| F1 | 0 | 1.0 |
| False Negative | 2 | 0 |
| False Positive | 0 | 0 |
| 탐지 latency 평균 | 측정 불가 | 8.09초 |
| 탐지 latency p95 | 측정 불가 | 12.62초 |

개별 latency는 약 13.12초와 3.06초다. 이 표는 파이프라인 회귀가 두 알려진 FN을 복구했다는 증거일 뿐, 새로운 방·사람·채널 일반화나 실제 운영 Precision을 증명하지 않는다. 첫 사건 지연 13.12초도 개선 대상이다. 결과 원본은 `data/processed/s3-before-after.json`에 저장된다.

## S3 데이터 수집·학습 규약

모든 세션은 `roomId`, `personId`, `positionId`, `activityId`, `deviceFamily=ESP32-S3`, channel/bandwidth, sampling stats, event cue, raw IQ를 남긴다. 최소 라벨은 전후좌우/느린/빠른 낙상과 collapse, 빠르게 앉기·눕기·숙이기, 걷기/달리기/점프, 물체 이동/낙하, empty room이다. 첫 목표는 최소 3개 방, 3명, 2개 이상 채널과 20개 이상 낙상 사건이지만, 95% Recall 신뢰구간을 좁히려면 훨씬 많은 locked fall events가 필요하다.

단순 row random split은 금지한다. 방/사람/채널 각각에 대해 서로 다른 group을 train, threshold validation, locked test로 둔다. threshold는 validation PR curve에서 Recall 95% 이상을 우선하고 그 안에서 Precision이 높은 값을 선택한다. locked test는 threshold 선택에 사용하지 않는다.

```bash
# 데이터 요건만 감사. 부족하면 exit 2와 publishable=false가 정상이다.
PYTHONPATH=gateway/src:. .venv/bin/python -m ml.s3.training

# 데이터 확보 후 후보별/그룹별 실험
PYTHONPATH=gateway/src:. .venv/bin/python -m ml.s3.training --model xgboost --group-key room_id
PYTHONPATH=gateway/src:. .venv/bin/python -m ml.s3.training --model tcn --group-key person_id
PYTHONPATH=gateway/src:. .venv/bin/python -m ml.s3.training --model cnn_gru --group-key channel
```

Gaussian noise, 0.9~1.1 amplitude scaling, 최대 5% packet dropout, 최대 10% carrier mask, 작은 baseline shift/time shift만 적용한다. class-balanced sampling, positive weighting과 focal loss를 제공한다. 첫 모델의 실제 FP/FN clip은 `hard_negative_v2`/추가 fall 데이터로 라벨링해 반복 학습한다.

## 완료되지 않은 성능 과제

- S3 locked test 기준 Recall 95% 달성 여부: 데이터 부족으로 미검증
- amplitude-only, +phase, +RSSI, calibration, fusion/model별 ablation: 그룹 데이터 확보 후 실행
- leave-one-room/person/channel-out 비교: 알려진 person metadata 0명으로 현재 불가
- 50/100/150/200 Hz packet density 비교: 현재 firmware/로컬 데이터는 약 100 Hz만 검증
- 첫 낙상 13초 지연: S3 5초 temporal model로 교체 후 목표 3~5초 이내 재평가
- 실제 일상 장시간 FP/day와 저품질 RF 조건 평가

위 항목이 끝나기 전에는 이 시스템을 의료기기 또는 안전 보장 장치로 표현하지 않는다.
