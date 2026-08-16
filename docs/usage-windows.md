# Windows 사용법

최종 확인일: 2026-08-17

처음 설치하는 PC는 먼저 [Windows 초기 세팅](setup-windows.md)을 완료한다. 보정,
공간 프로필, 화면 지표와 수집 규칙의 상세 설명은 [공통 사용법](usage.md)에 있다.

## 포트 확인

PowerShell을 프로젝트 루트에서 연다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\python.exe -m csi_gateway ports
```

`USB-Enhanced-SERIAL CH343` 또는 `VID:PID=1A86:55D3`인 포트를 확인한다.
아래 명령의 `COM8`은 RX, `COM7`은 TX 예시이므로 실제 번호로 바꾼다.

## 매일 실행

```powershell
.\scripts\start-radar-monitor.ps1 -Port COM8
```

모니터는 `ml\v_main\model.pt`를 불러오고, RX에 raw CSI 출력을 자동으로
활성화한다. 모니터, 수집기와 다른 시리얼 프로그램은 같은 RX 포트를 동시에
열 수 없다.

낙상 후보가 발생하면 `최근 낙상 후보·감지 기록`에서 감지 시각, 신뢰 지표,
Radar/ML 근거와 앱 전달 상태를 확인할 수 있다. 앱 서버가 없어도 기록은
`data\events\YYYY-MM-DD.jsonl`에 남는다.

모델만 먼저 점검하려면:

```powershell
.\.venv\Scripts\python.exe -m csi_gateway activity-model-check --project-root .
```

## 빈방 CSI 5분 수집

모니터를 닫고 방을 비우기 전에 보드와 움직이는 물체를 고정한다.

```powershell
.\scripts\collect.ps1 `
  -Port COM8 `
  -Label empty_room `
  -Duration 300 `
  -RoomId room-01 `
  -DeviceId rx-s3-001
```

결과는 `data\raw\<session-id>.jsonl`과
`data\manifests\<session-id>.json`에 생긴다. JSONL에 `CSI_DATA,`가 반복되고
104개 raw I/Q 정수가 보이는지 확인한다.

## prebuilt 펌웨어 다시 올리기

평소에는 반복할 필요가 없다. 펌웨어가 지워졌거나 보드를 교체했을 때만 실행한다.

```powershell
.\scripts\flash-prebuilt.ps1 -Role tx -Port COM7
.\scripts\flash-prebuilt.ps1 -Role rx -Port COM8
```

TX/RX 모두 ESP32-S3, HT20, 기본 채널 6이며 TX 송신 주기는 10ms(100Hz)다.
플래시 스크립트는 ESP-IDF 소스나 `third_party\esp-csi` 없이 동작한다.

## 공식 Espressif GUI

필요한 경우에만 실행한다.

```powershell
.\scripts\start-csi-gui.ps1 -Port COM8
```

공식 GUI와 프로젝트 모니터는 같은 RX 포트를 동시에 사용할 수 없다.

## 문제 해결

- `Access is denied` 또는 포트 사용 중: 모니터, 수집기, 공식 GUI와 시리얼 터미널을 닫는다.
- 포트가 없음: 데이터 가능한 USB 케이블, `UART` 단자와 CH34x 드라이버를 확인한다.
- 글자가 깨짐: RX baud를 반드시 `2000000`으로 사용한다.
- COM 번호가 바뀜: 정상이다. `ports`를 다시 실행하고 명령의 번호만 바꾼다.
