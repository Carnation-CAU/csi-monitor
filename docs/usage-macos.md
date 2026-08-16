# macOS 사용법

최종 확인일: 2026-08-17

처음 설치하는 Mac은 먼저 [macOS 초기 세팅](setup-macos.md)을 완료한다. 보정,
공간 프로필, 화면 지표와 수집 규칙의 상세 설명은 [공통 사용법](usage.md)에 있다.

## 현재 연결된 보드

이 Mac에서 2026-08-17에 확인하고 HT20 펌웨어를 올린 포트다.

| 역할 | 포트 |
|---|---|
| RX | `/dev/cu.usbmodem5CCD0332951` |
| TX | `/dev/cu.usbmodem5CCD0309411` |

USB 위치가 바뀌면 포트 이름도 바뀔 수 있으므로 매번 다시 확인한다.

```bash
cd /Users/yarlang/startup-competition
.venv/bin/python -m csi_gateway ports
```

## 매일 실행

TX에 전원을 공급하고 RX를 Mac에 연결한 뒤 실행한다.

```bash
cd /Users/yarlang/startup-competition
./scripts/start-radar-monitor.sh /dev/cu.usbmodem5CCD0332951
```

모니터는 `ml/v_main/model.pt`를 불러오고, RX에 raw CSI 출력을 자동으로
활성화한다. 모니터, 수집기와 다른 시리얼 프로그램은 같은 RX 포트를 동시에
열 수 없다.

낙상 후보가 발생하면 `최근 낙상 후보·감지 기록`에서 감지 시각, 신뢰 지표,
Radar/ML 근거와 앱 전달 상태를 확인할 수 있다. 앱 서버가 없어도 기록은
`data/events/YYYY-MM-DD.jsonl`에 남는다.

모델만 먼저 점검하려면:

```bash
.venv/bin/python -m csi_gateway activity-model-check --project-root .
```

## 빈방 CSI 5분 수집

모니터를 닫고, 방을 비우기 전에 보드와 움직이는 물체를 고정한다.

```bash
./scripts/collect.sh /dev/cu.usbmodem5CCD0332951 empty_room 300
```

또는 모든 식별자를 직접 지정한다.

```bash
.venv/bin/python -m csi_gateway collect \
  --port /dev/cu.usbmodem5CCD0332951 \
  --baud 2000000 \
  --duration 300 \
  --label empty_room \
  --room-id room-01 \
  --device-id rx-s3-001 \
  --project-root .
```

결과는 `data/raw/<session-id>.jsonl`과
`data/manifests/<session-id>.json`에 생긴다. JSONL에 `CSI_DATA,`가 반복되고
104개 raw I/Q 정수가 보이는지 확인한다.

## prebuilt 펌웨어 다시 올리기

평소에는 반복할 필요가 없다. 펌웨어가 지워졌거나 보드를 교체했을 때만 실행한다.

```bash
./scripts/flash-prebuilt.sh tx /dev/cu.usbmodem5CCD0309411
./scripts/flash-prebuilt.sh rx /dev/cu.usbmodem5CCD0332951
```

TX/RX 모두 ESP32-S3, HT20, 기본 채널 6이며 TX 송신 주기는 10ms(100Hz)다.
플래시 스크립트는 ESP-IDF 소스나 `third_party/esp-csi` 없이 동작한다.

## 현재 펌웨어 검증 결과

2026-08-17 실제 보드에서 다음을 확인했다.

- TX/RX 플래시 후 쓰기 해시 검증 통과
- RX 채널 `6`
- raw CSI 길이 `104` = 52개 I/Q 쌍
- 장치 timestamp 간격 약 `10,000us` = 약 100Hz
- `CSI_DATA`와 `RADAR_DADA` 동시 출력

채널을 바꾸면 TX/RX가 함께 바뀌어야 한다. 자체 실험 데이터는 선택한 한 채널로
고정하고, 채널이나 배치를 바꾸면 새 보정과 새 세션으로 관리한다.

## 문제 해결

- `Operation not permitted`: 터미널 또는 실행 앱에 USB/장치 접근 권한을 허용한다.
- `port is busy`: 모니터, 수집기, `screen`, 시리얼 GUI 중 먼저 연 프로그램을 닫는다.
- 포트가 없음: 데이터 가능한 USB 케이블과 `UART` 단자를 확인하고 `ports`를 다시 실행한다.
- 글자가 깨짐: RX baud를 반드시 `2000000`으로 사용한다.
