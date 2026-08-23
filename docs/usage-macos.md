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
`낙상 알림 서버`의 기본값은 `http://localhost:8080`이다.
이 JSONL은 원시 CSI가 아니라 자동 감지·알림 이벤트 기록이다. 평상시에는
`실시간 모니터링` 탭의 큰 그래프와 오른쪽 낙상 이력을 확인하고, 보정과 수집
기능은 각각 별도 탭에서 사용한다.

실제 몸으로 넘어지지 않고 전체 경로를 확인하려면 `행동 데이터 수집` 탭에서
`알림 경로 시뮬레이션 (센서 제외)`을 누른다. 이 버튼은 Radar 후보가
먼저이고 ML 후보가 나중인 순서의 양방향 융합, 감지 경고음, JSONL 기록과 앱
전송을 시험한다. 서버 주소가 비어 있어도 로컬 시험은 즉시 실행된다. 실시간 탭의
`낙상 후보·최종 감지 소리`가 켜져 있으면 후보는 1회, 최종 낙상 의심은 3회 울린다.
ML이 S3 침대 낙상을 놓치는 동안 임시 보조 경보가 필요하면 실시간 탭의
`실험적 Radar 단독 보조 알림`을 직접 켠다. 오탐 가능성이 있어 기본값은 꺼짐이다.
그래프는 최근 10분을 보관한다. 과거를 보려면 그래프를 가로로 드래그하거나
`← 이전 30초`를 누르고, 다시 실시간으로 돌아갈 때는 `현재로`를 누른다.

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

결과는 `data/raw/empty_room/<session-id>.jsonl`과
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

GUI에서는 초록색 `실제 RF 검증됨`과 `CSI 채널 6`, `RX 응답 6`,
`Bandwidth HT20 (cwb=0)`, `secondary 0`을 확인한다. 이 표시는 고정 문구가
아니라 수신 중인 CSI 메타데이터에서 계산되며 CSI가 끊기면 `확인 불가`로 바뀐다.

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
