# 공개 Wi-Fi CSI 행동 데이터셋 후보

조사일: 2026-08-11

이 문서는 행동 분류 실험에 사용할 공개 데이터셋 후보와 현재 프로젝트에 대한
적합성을 정리한다. 원본 데이터는 용량과 라이선스 때문에 저장소에 커밋하지 않고
`ml/dataset/raw/` 아래에 로컬로만 둔다.

## 먼저 알아야 할 호환성 한계

현재 프로젝트의 주 입력은 ESP32-S3 RX에서 Espressif Radar가 출력하는 다음
시계열이다.

```text
wander, someone_threshold, someone_status,
jitter, move_threshold, move_status
```

공개 데이터셋 대부분은 이 값이 아니라 다음 형태를 제공한다.

```text
시간 x 안테나 x 서브캐리어의 복소 CSI 또는 CSI amplitude
```

따라서 공개 데이터의 분산이나 차분을 프로젝트의 `jitter`라는 이름으로 바꾸면
안 된다. Espressif Radar의 내부 계산과 빈 공간 보정을 재현하지 못하기 때문이다.
공개 데이터와 우리 데이터를 함께 쓰려면 다음 중 하나를 택해야 한다.

1. **공통 raw-CSI 표현:** 양쪽 데이터를 `time x subcarrier amplitude`로 만들고
   같은 모델에 입력한다. 이 경로는 우리 ESP32 수집에도 `CSI_DATA`의 I/Q 배열이
   실제로 저장되는지 먼저 확인해야 한다.
2. **공통 파생 표현:** 각 데이터셋에서 시간 변화량, rolling dispersion,
   subcarrier energy 같은 장치 독립 후보 특징을 계산한다. 이 값은
   `motion_energy`처럼 새 이름을 사용하고 `jitter`와 동일하다고 주장하지 않는다.
3. **사전학습 후 미세조정:** 공개 raw CSI로 시계열 인코더를 사전학습하고,
   최종 분류기는 우리 ESP32 데이터로 다시 학습·보정한다.

공개 데이터만으로 학습한 모델을 현재 `wander/jitter` 입력에 바로 적용하는 것은
불가능하다. 공개 데이터는 모델 구조 검증과 사전학습에 유용하지만, 최종 성능은
반드시 우리 하드웨어·방·배치 데이터로 평가해야 한다.

## 우선순위 요약

| 순위 | 후보 | 장비/표현 | 관련 행동 | 현재 판단 |
|---:|---|---|---|---|
| 1 | ESP-Fi HAR | ESP32, amplitude `1x950x52` | fall, walk, turn, squat 등 7개 | 첫 실험에 가장 적합 |
| 2 | UT-HAR | Intel 5300 계열, amplitude `1x250x90` | lie down, fall, walk, pickup, sit/stand 등 7개 | 라벨 적합성이 가장 높음 |
| 3 | OPERAnet | Intel 5300, 연속 `.mat`와 시간 라벨 | walk, sit, stand, liedown, standfromlie, bodyrotate | 이벤트 구간 학습에 유용 |
| 4 | ESP32 Through-Wall HAR | ESP32, amplitude spectrogram 이미지 | no activity, walking, walking+arm wave | 장비는 가깝지만 라벨이 부족 |
| 5 | Widar 3.0 | Intel 5300, CSI/DFS/BVP, 6 RX | 제스처와 보행 | 교차 공간 연구용, 초기 분류에는 과함 |
| 6 | WiAR | Intel 5300 raw `.dat`, 30 Hz, 3 안테나 | walk, sit down, squat, bend 등 16개 | 유용하지만 라이선스 불명확 |
| 7 | CSI-Bench | 16종 상용 장치, 장시간 연속 CSI | fall, HAR, proximity 등 | 매우 유망하나 접근·용량 확인 필요 |
| 보류 | WiPE-FaLl | USRP X300 amplitude | 낙상 위험도별 보행 | 실제 행동/낙상 분류가 아니며 요청형 데이터 |

## 1. ESP-Fi HAR — 최우선

- 원문: <https://github.com/AutoSmartGroup/ESP-Fi-HAR>
- 장비: 저전력 ESP32 모듈
- 표현: CSI amplitude, 샘플당 `1 x 950 x 52`
- 규모: 4개 실내 환경, 8명, 7행동, 10회 반복, 총 2,240개 샘플
- 행동: `run`, `fall`, `walk`, `turn`, `jump`, `squat`, `arm wave`
- 형식: `.mat`, 파일명에 환경·참가자·행동·반복 번호 포함
- 데이터 라이선스: CC BY 4.0
- 코드 라이선스: MIT

장점:

- 후보 중 우리 ESP32-S3 구성과 하드웨어 계열이 가장 가깝다.
- 사람과 환경 ID가 있어 사람/공간 단위 평가 분할이 가능하다.
- `fall`, `walk`가 직접 포함되어 있다.
- 원시 amplitude 행렬이 있어 자체 전처리를 시험할 수 있다.

한계:

- 현재 프로젝트의 `wander/jitter` 출력과 동일한 값은 아니다.
- `turn`은 서서 방향을 바꾸는 행동일 수 있으므로 `turn_in_bed`로 매핑하면 안 된다.
- 제공 benchmark는 validation 없이 학습 정확도로 best model을 선택하므로 그 평가
  절차를 그대로 따르지 않는다.

판정: **가장 먼저 다운로드 구조와 한 샘플의 배열/메타데이터를 검증할 후보.**

## 2. UT-HAR — 라벨 기준선

- 원본 코드/데이터 안내: <https://github.com/ermongroup/Wifi_Activity_Recognition>
- 처리본/통합 benchmark: <https://github.com/xyanchen/WiFi-CSI-Sensing-Benchmark>
- 장비: Linux 802.11n CSI Tool 기반 Intel 5300 계열
- 원본 표현: 30 subcarrier x 3 antenna의 amplitude 90개와 phase 90개
- SenseFi 처리본: 샘플당 amplitude `1 x 250 x 90`
- 처리본 규모: train 3,977개, test 996개
- 행동: `lie down`, `fall`, `walk`, `pickup`, `run`, `sit down`, `stand up`

장점:

- 우리의 목표 행동과 가장 많이 겹친다.
- 기존 benchmark loader와 여러 기준 모델을 참고할 수 있다.
- 눕기와 낙상을 별도 라벨로 비교할 수 있다.

한계:

- ESP32가 아니라 Intel 5300의 3안테나 CSI다.
- 기존 train/test가 참가자·세션 누수를 방지하는 분할인지 별도로 확인해야 한다.
- 코드 라이선스(GPL-3.0 또는 benchmark의 MIT)가 데이터 라이선스를 대신하지
  않는다. 데이터의 사용 조건은 원 배포처에서 추가 확인해야 한다.

판정: **ESP-Fi HAR 다음으로 baseline을 만들기 좋은 후보. 라이선스 확인 전에는
외부 재배포 금지.**

## 3. OPERAnet — 연속 행동과 이벤트 분할

- 논문 및 데이터 설명: <https://www.nature.com/articles/s41597-022-01573-2>
- 데이터 DOI: <https://doi.org/10.6084/m9.figshare.c.5551209.v1>
- 장비: Intel 5300 NIC 송신기 1대와 수신기 2대
- 규모: 약 8시간, 2개 방, 최대 6명, 100만 개 이상의 시간 주석 표본
- 형식: Wi-Fi CSI `.mat`, 한 행이 수신 패킷
- 라벨: `background`, `walk`, `sit`, `stand`, `liedown`,
  `standfromlie`, `bodyrotate`, `noactivity`

장점:

- 짧게 잘린 샘플만이 아니라 시간 단위 주석이 있어 이벤트 전·중·후 윈도우를
  만드는 실험에 적합하다.
- `liedown`과 `standfromlie`가 우리 목표에 직접 대응한다.
- 방과 참가자를 분리한 일반화 평가를 설계할 수 있다.

한계:

- Intel 5300의 30-subcarrier CSI이며 ESP32와 도메인 차이가 크다.
- 여러 모달리티 전체를 받을 필요 없이 Wi-Fi CSI 부분만 선택해야 한다.
- 다운로드 전에 Figshare 레코드의 현재 라이선스를 직접 재확인한다.

판정: **이벤트 구간 추출 방식과 시계열 모델을 검증할 때 높은 가치가 있다.**

## 4. ESP32 Long-Range Through-Wall HAR

- 데이터: <https://zenodo.org/records/8021099>
- 장비: ESP32, 100 Hz
- 규모: LOS/NLOS, 총 776개 activity spectrogram
- 행동 라벨: `no activity`, `walking`, `walking + arm-waving`
- 표현: 4초/400패킷 CSI amplitude spectrogram 이미지
- 조건: 비상업 연구 용도만 허용한다고 명시

장점:

- ESP32와 100 Hz라는 점이 우리 송신 설정과 가깝다.
- LOS/NLOS와 여러 방이 포함되어 환경 변화 시험에 도움이 된다.

한계:

- 원시 I/Q나 amplitude 배열이 아니라 이미 생성된 spectrogram 이미지 중심이다.
- 행동이 세 종류뿐이고 눕기·일어나기·낙상이 없다.
- 비상업 제한이 있어 제품 모델에 직접 사용하는 것은 부적합하다.

판정: **ESP32 도메인의 작은 보조 실험용. 주 학습 데이터로는 부족하다.**

## 5. Widar 3.0 — 교차 도메인 연구용

- 공식 페이지: <https://tns.thss.tsinghua.edu.cn/widar3.0/>
- 공개 데이터: <https://ieee-dataport.org/open-access/widar-30-wifi-based-activity-recognition-dataset>
- 장비: Intel 5300 기반 다중 링크, 최대 6개 수신기
- 표현: raw CSI `.dat`, DFS `6 x 121 x T`, BVP `20 x 20 x T`
- 메타데이터: 사용자, 방, 위치, 방향, 반복, 수신기 ID

장점:

- 사용자·방·위치·방향 변화가 명시되어 교차 도메인 평가에 강하다.
- raw CSI뿐 아니라 속도와 관련된 DFS/BVP 표현을 비교할 수 있다.

한계:

- 다중 수신기와 BVP 파이프라인이 현재 단일 TX/RX ESP32 구성보다 훨씬 복잡하다.
- 주 목적이 제스처 인식이므로 눕기·일어나기 분류와 직접 맞지 않는다.
- 구형 MATLAB/Python/Keras 도구를 그대로 재사용하기 어렵다.
- IEEE DataPort의 현재 이용 조건을 다운로드 전에 확인해야 한다.

판정: **초기 모델이 완성된 뒤 공간·방향 일반화 연구에 사용.**

## 6. WiAR — 행동 종류는 좋지만 법적 상태 확인 필요

- 원문: <https://github.com/linteresa/WiAR>
- 장비: T400 노트북, Intel 5300, 3안테나, 30 Hz
- 표현: Linux 802.11n CSI Tool raw `.dat`
- 공개 범위: 설명은 10명 x 행동당 30회를 말하지만 저장소에는 3명 데이터만
  공개됐다고 명시
- 행동: 팔 흔들기, 던지기, 차기, 굽히기, 박수, 걷기, 앉기, 스쿼트 등 16개

장점:

- `walk`, `sit down`, `squat`, `bend`가 있어 유사 행동 오탐 비교에 쓸 수 있다.
- raw CSI와 MATLAB 파서가 함께 제공된다.

한계:

- ESP32와 장비·안테나·표본률이 다르다.
- 눕기·일어나기·낙상이 없다.
- 저장소에 명시적인 데이터 라이선스가 보이지 않는다.

판정: **라이선스 허가를 확인하기 전에는 탐색·재현 연구만 고려하고, 학습된
제품 모델이나 데이터 재배포에는 사용하지 않는다.**

## 7. SenseFi benchmark — 데이터셋이 아닌 비교 도구

- 원문: <https://github.com/xyanchen/WiFi-CSI-Sensing-Benchmark>
- 포함 loader: UT-HAR, NTU-Fi HAR, NTU-Fi HumanID, Widar
- 모델: MLP, CNN/ResNet, RNN/GRU/LSTM, CNN+GRU, ViT
- 코드 라이선스: MIT

장점:

- 여러 CSI 배열 형식을 PyTorch 입력으로 만드는 loader를 비교할 수 있다.
- 동일한 모델군을 여러 공개 데이터에 적용한 기준선이다.

주의:

- 이 저장소 자체가 하나의 새 데이터셋은 아니다.
- Google Drive 처리본은 원 데이터의 라이선스와 출처를 각각 따라야 한다.
- Windows 경로를 직접 수정하도록 되어 있어 코드를 그대로 복사하지 않는다.

판정: **모델·loader 참고용. 데이터 출처로 인용할 때는 각 원 데이터셋을 인용.**

## 8. CSI-Bench — 장기 추적 후보

- 논문: <https://arxiv.org/abs/2505.21866>
- 규모: 461시간 이상, 35명, 26개 환경, 16종 장치 구성
- 작업: fall detection, HAR, breathing, localization, motion source,
  identity/proximity 공동 라벨
- 장치: Qualcomm, MediaTek, Broadcom, Espressif, NXP 등 이기종 장치

장점:

- 실제 환경, 연속 기록, 낙상 데이터와 이기종 장치를 함께 다룬다는 점에서
  최종 목표와 가장 가깝다.
- Espressif 계열 장치도 포함한다.

한계:

- 데이터 크기가 초기 실험용으로 지나치게 크다.
- 조사 시점에 공개 다운로드 위치와 세부 라이선스를 원문에서 확정하지 못했다.
- 장치별 CSI 배열을 공통화하는 추가 작업이 필요하다.

판정: **다운로드·라이선스가 확인되면 장기적으로 매우 높은 가치. 지금은 추적 후보.**

## 보류 후보

### WiPE-FaLl

- 원문: <https://researchdata.gla.ac.uk/1623/>
- USRP X300 한 쌍으로 한 명의 TUG 보행을 수집했다.
- 목표는 실제 낙상 행동 분류가 아니라 낮음/중간/높음 낙상 위험 보행 분류다.
- CC BY 4.0이지만 데이터는 요청 방식이다.

현재 행동 분류 목표와 직접 맞지 않아 우선순위를 낮춘다.

### Wi-Fi CSI/RSS presence and movement dataset

- 원문: <https://zenodo.org/records/3677353>
- Intel CSI Tool 기반 CSI/RSS와 presence/movement 주석을 제공한다.
- 약 28 GB로 크고 행동 종류 분류보다 사람 존재·움직임 검출에 가깝다.

친구가 담당하는 사람 존재 모델에는 후보가 될 수 있지만 현재 행동 분류의
우선 데이터로는 사용하지 않는다.

## 라벨 매핑 원칙

데이터셋마다 이름이 같아 보여도 동작 정의가 다를 수 있으므로 자동으로 합치지
않는다. 원본 라벨을 보존하고, 검토된 매핑을 별도 필드로 둔다.

| 원본 라벨 | 임시 공통 라벨 | 주의사항 |
|---|---|---|
| `walk`, `walking` | `walking` | 속도와 경로 차이는 메타데이터로 유지 |
| `lie down`, `liedown`, `bed` | `lie_down` | 시작·종료 자세 확인 필요 |
| `standfromlie` | `get_up_from_lying` | 일반 `stand up`과 구분 |
| `stand up` | `stand_up` | 앉은 자세 출발일 수 있음 |
| `fall` | `fall` | 방향, 매트 사용, 종료 자세 확인 필수 |
| `pickup`, `bend` | `pick_up_or_bend` | 두 행동을 처음부터 동일시하지 않음 |
| `turn` | `turn` | `turn_in_bed`로 매핑 금지 |
| `run`, `jump`, gesture | `other_motion` | 초기 타깃 밖의 음성 클래스 후보 |

`fall`을 우리 프로젝트의 `fall_simulated_mattress`와 바로 동일시하지 않는다.
수행 방식과 안전 조건이 다르기 때문이다.

## 공통 전처리 초안

첫 구현 전에는 아래 최소 표현만 검증한다.

```text
sample_id
source_dataset
source_label
target_label (검토 후에만 채움)
participant_id
environment_id
trial_id
sample_rate_hz
amplitude: float[T, S]
```

- 복소 CSI가 있으면 `amplitude = sqrt(I^2 + Q^2)`를 계산한다.
- 안테나가 여러 개면 처음에는 링크를 임의 평균하지 말고 링크 축을 보존한다.
- 길이는 원본을 보존하고 모델 입력 직전에만 crop/pad/resample한다.
- 정규화 통계는 train split에서만 계산한다.
- train/validation/test는 window가 아니라 참가자·세션·환경 단위로 나눈다.
- 처리 결과에서 원본 파일과 변환 설정을 역추적할 수 있어야 한다.

ESP32 공개 데이터와 Intel 5300 데이터를 섞어 무작위 분할하면 모델이 행동이
아니라 장치 종류를 학습할 수 있다. 반드시 `source_dataset` 또는 장치 도메인
전체를 분리한 평가를 포함한다.

## 추천 실행 순서

1. ESP-Fi HAR의 `.rar`에서 샘플 몇 개만 열어 실제 `.mat` key, dtype,
   `950 x 52` 방향과 라벨 파일을 확인한다.
2. UT-HAR 처리본에서 샘플 몇 개를 열어 `250 x 90` 배열과 split 메타데이터를
   확인한다.
3. 두 데이터셋을 합치지 않고 각각 동일한 작은 CNN/Random Forest 기준선을 만든다.
4. 원본 라벨별 confusion matrix와 참가자/환경 분할 가능 여부를 확인한다.
5. 우리 ESP32 JSONL에 raw `CSI_DATA`가 실제로 포함되는지 조사한다.
6. raw CSI가 있으면 공통 amplitude 표현을 시험하고, 없다면 공개 데이터
   사전학습과 Radar `wander/jitter` 최종 모델을 별도 경로로 유지한다.

첫 다운로드 대상으로는 **ESP-Fi HAR**, 첫 라벨 기준 비교 대상으로는
**UT-HAR**, 이벤트 구간 연구 대상으로는 **OPERAnet**을 권장한다.
