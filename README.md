# ESP32-S3 Wi-Fi CSI 안전 모니터링

Windows에서 먼저 개발하고 동일한 데이터·분석 코드를 macOS에서 실행하기 위한 프로젝트다.

초기 목표:

```text
ESP32-S3 송신기 → ESP32-S3 CSI 수신기 → PC 수집기
→ 움직임 감지 → 낙상 의심 이벤트 → 서버 → Android 알림
```

## 현재 포함된 기본 세팅

- Windows/macOS 공용 Python CSI 직렬 수집기
- 버전이 지정된 JSON Lines 원본 저장 형식
- 세션 manifest 생성
- 직렬 포트 검색 명령
- 운영체제별 부트스트랩과 수집 스크립트
- parser 및 경로 호환성 자동 테스트
- 공식 Espressif `esp-csi`를 둘 `third_party` 구조
- 현재 채널 표시와 채널 1·6·11 자동 비교
- 빈 공간 보정과 움직임·정지 실시간 확인

## 빠른 시작 — Windows

python.org의 Windows용 Python 3.12를 사용한다.

```powershell
.\scripts\bootstrap.ps1
.\.venv\Scripts\Activate.ps1
python -m csi_gateway ports
python -m csi_gateway collect --port COM4 --label empty_room --duration 120
python -m unittest discover -s gateway\tests -v
```

ESP-IDF 환경은 새 PowerShell에서 다음처럼 활성화한다.

```powershell
. .\scripts\activate-idf.ps1
idf.py --version
```

펌웨어는 이미 ESP32-S3 대상으로 빌드 검증되어 있다. 보드 연결 후 포트를 확인하고 각각 업로드한다.

```powershell
python -m csi_gateway ports
.\scripts\flash-sender.ps1 -Port COM3
.\scripts\flash-receiver.ps1 -Port COM4
.\scripts\start-csi-gui.ps1 -Port COM4
```

PowerShell 실행 정책 때문에 스크립트가 차단되면 현재 프로세스에만 허용한다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## 빠른 시작 — macOS

```bash
git clone https://github.com/Carnation-CAU/Dev.git startup-competition
cd startup-competition
chmod +x scripts/*.sh
./scripts/bootstrap.sh
. .venv/bin/activate
python -m csi_gateway ports
./scripts/start-radar-monitor.sh /dev/cu.wchusbserial-RECEIVER
python -m unittest discover -s gateway/tests -v
```

수정된 ESP-CSI 펌웨어 소스까지 준비하려면 다음을 추가로 실행한다.

```bash
./scripts/fetch-esp-csi.sh
```

## 펌웨어

최초 검증은 Espressif 공식 예제를 사용한다.

- 송신기: `third_party/esp-csi/examples/get-started/csi_send`
- 수신기: `third_party/esp-csi/examples/esp-radar/console_test`

## 문서

새 PC에서 처음 세팅한다면 아래 문서를 순서대로 따라간다. 둘 다 클론부터 보드 확인까지 전체를 다룬다.

- [Windows 초기 세팅](docs/setup-windows.md)
- [macOS 초기 세팅](docs/setup-macos.md)

## 브랜치

| 브랜치 | 용도 |
|---|---|
| `main` | 초기 세팅본. setup 문서대로 따라가면 동작하는 기준 상태 |
| `dev` | 개발 통합 브랜치 |
| `dev`에서 파생 | 각자 작업 브랜치 |

## 데이터 취급

수집 데이터(`data/raw`, `data/manifests`, `data/processed`)와 공간 프로필(`data/profiles`)은
방 배치·보드 MAC·생활 패턴 같은 개인 환경 정보를 담으므로 저장소에 올리지 않는다.
각자 자신의 PC에서 생성해 사용한다.

그 밖의 절차는 [개발 환경](docs/environment.md), [사용법](docs/usage.md),
[실험 규약](docs/experiment-protocol.md), [성장 및 추가 개발 로드맵](docs/growth-roadmap.md)을 참고한다.

## 안전 및 표현 원칙

- 시스템 출력은 `낙상`이 아니라 `낙상 의심(FALL_SUSPECTED)`으로 표현한다.
- 고령자에게 모의 낙상을 수행하게 하지 않는다.
- 원본 CSI는 수정하지 않고 파생 데이터는 별도 버전으로 생성한다.
- 실제 사람/세션 단위로 학습·검증·테스트를 분리한다.
