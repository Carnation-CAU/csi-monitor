# Windows 초기 세팅

새 Windows PC에서 이 프로젝트를 처음 실행할 때의 순서다. 위에서부터 차례대로 진행한다.
현재 환경 기준값은 [개발 환경](environment.md), 매일 쓰는 사용 절차는 [사용법](usage.md)을 참고한다.

## 이 문서의 범위

| 단계 | 필요한 경우 |
|---|---|
| 1~4장 | 항상 필요 |
| 5장 (펌웨어 업로드) | **새로 산 보드라면 필수.** 펌웨어는 PC가 아니라 보드 안에 들어간다. |
| └ 5-A 또는 5-B | **둘 중 하나만.** ESP-IDF는 5-B에서만 필요하다 |
| 6장 이후 | 펌웨어를 업로드한 뒤의 실행 절차 |

이미 펌웨어가 올라간 보드를 넘겨받았다면 5장을 건너뛰고 6장으로 간다. **새 보드를 구매했다면 5장을 반드시 거쳐야 하며, 그 전까지는 보드에서 아무 데이터도 나오지 않는다.**

## 0. 준비물

- Windows 10/11
- Git
- Python 3.10 이상 (펌웨어를 빌드한다면 3.12 권장 — [2장](#2-python-설치) 참고)
- USB-C 케이블, TX용 보조배터리
- ESP32-S3 보드 2개 (TX 송신기, RX 수신기)

### 보드 구매 시 확인할 것

개발 PC의 검증된 구성은 **ESP32-S3, revision 0.2, embedded PSRAM 8 MB** 보드 2개다. 새로 구매한다면 다음을 확인한다.

| 항목 | 요구 사항 | 이유 |
|---|---|---|
| 칩 | ESP32-S3 | 펌웨어 타겟이 `esp32s3`로 고정 |
| **RX 보드의 USB-UART 브리지** | **CH343/CH340/CP2102 등 탑재 필수** | RX 콘솔이 UART0(GPIO 43/44), 2,000,000 baud로 설정됨 |
| TX 보드 | 전원만 공급되면 됨 | TX는 PC에 연결하지 않음 |

RX는 특히 주의한다. `sdkconfig`가 다음과 같이 고정돼 있다.

```text
CONFIG_ESP_CONSOLE_UART_CUSTOM_NUM_0=y
CONFIG_ESP_CONSOLE_UART_TX_GPIO=43
CONFIG_ESP_CONSOLE_UART_RX_GPIO=44
CONFIG_ESP_CONSOLE_UART_BAUDRATE=2000000
```

즉 **RX 데이터는 GPIO 43/44에 물린 USB-UART 브리지로 나온다.** 개발 PC의 RX 보드는 USB-C 단자가 두 개이며 그중 `UART` 쪽(CH343)을 사용한다. native USB(USB-Serial-JTAG) 단자만 있는 보드는 이 프로젝트에서 검증되지 않았으므로 피한다.

## 1. 저장소 클론

```powershell
Set-Location $HOME\Desktop
git clone https://github.com/Carnation-CAU/Dev.git startup-competition
Set-Location startup-competition
```

프로젝트 경로에 한글이나 공백이 없는 편이 안전하다.

### 브랜치 규칙

| 브랜치 | 용도 |
|---|---|
| `main` | 초기 세팅본. 이 문서대로 따라가면 동작하는 기준 상태 |
| `dev` | 개발 통합 브랜치 |
| `dev`에서 파생 | 각자 작업 브랜치 |

세팅만 확인할 때는 `main` 그대로 두고, 개발을 시작할 때 `dev`에서 작업 브랜치를 만든다.

```powershell
git checkout dev
git pull
git checkout -b feature/작업이름
```

## 2. Python 설치

python.org의 **Windows용 Python**을 설치하고 설치 화면에서 `Add python.exe to PATH`를 체크한다.

### 어느 버전을 쓸까

**3.10 이상이면 동작한다.** 어떤 버전을 고를지는 펌웨어를 빌드할지에 달려 있다.

| 상황 | 권장 버전 |
|---|---|
| 수집·모니터만 사용 | **3.10 이상 아무 버전** (3.13, 3.14 포함) |
| 펌웨어도 빌드 (5-B) | **3.12** |

`pyproject.toml`의 요구 사항은 `>=3.10`이고, 검증된 버전은 `3.12`다. PC 게이트웨이가 쓰는 의존성(PyQt5, numpy, pandas, scipy, pyqtgraph)은 3.13·3.14용 Windows wheel이 모두 제공되므로 설치에 문제가 없다.

다만 **ESP-IDF v5.0.2는 3.12까지를 기준으로 구성**했다. 5-B로 펌웨어를 직접 빌드할 계획이라면 3.12를 설치하는 편이 안전하다. 이미 3.13이나 3.14를 쓰고 있어도 3.12를 함께 설치할 수 있으며, 두 버전은 공존한다.

### 확인

```powershell
py -0p
```

설치된 Python 목록이 나온다. 특정 버전을 확인하려면:

```powershell
py -3.12 --version
```

`bootstrap.ps1`은 3.12가 있으면 우선 사용하고, 없으면 3.13 → 3.14 → 3.11 → 3.10 순으로 찾는다. 실행할 때 어떤 버전을 골랐는지 첫 줄에 출력한다.

```text
사용할 Python: 3.12.10
```

MSYS/Git Bash에 딸린 Python은 사용하지 않는다. 부트스트랩 스크립트가 이를 감지하면 오류를 낸다.

## 3. Python 환경 구성

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap.ps1
```

`.venv`가 만들어지고 `pyserial`, `PyQt5`, `pyqtgraph`, `numpy`, `pandas`, `scipy`가 설치된다.

설치 확인:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s gateway\tests -v
```

모든 테스트가 통과해야 다음으로 넘어간다.

`Set-ExecutionPolicy -Scope Process Bypass`는 현재 PowerShell 창에만 적용된다. 새 창을 열 때마다 다시 실행하거나 `.\.venv\Scripts\python.exe -m csi_gateway ...` 형태로 직접 호출한다.

## 4. 보드 연결과 포트 확인

1. TX 송신기를 보조배터리나 USB 전원에 연결한다. 작은 빨간 LED가 전원 표시다. RGB LED는 켜지지 않아도 정상이다.
2. RX 수신기의 `UART` USB-C 단자를 PC에 연결한다.
3. TX와 RX를 USB 선으로 서로 연결하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m csi_gateway ports
```

RX 데이터 포트는 다음으로 식별한다.

```text
USB-Enhanced-SERIAL CH343
VID:PID=1A86:55D3
```

`VID:PID=303A:1001`인 Espressif native USB 포트는 RX UART 포트가 아니다.

개발 PC 기준 포트는 TX `COM7`, RX `COM8`이지만 **COM 번호는 PC와 USB 단자마다 다르다.** 이후 명령의 포트는 위 명령이 알려준 실제 번호로 바꾼다. 이 문서의 `COM8`은 RX 예시다.

## 5. 펌웨어 업로드 (새 보드라면 필수)

새로 산 보드에는 이 프로젝트의 펌웨어가 없다. 업로드 전에는 `ports`에 포트가 보여도 Radar 데이터가 전혀 나오지 않는다.

### 5-A와 5-B 중 하나만 한다

두 경로는 **택일**이다. 둘 다 할 필요 없고, 결과는 "보드에 펌웨어가 올라간 상태"로 같다. 차이는 그 `.bin`을 남이 빌드했느냐 내가 빌드했느냐뿐이다.

```text
5-B:  C 소스 ──[ESP-IDF v5.0.2]──> .bin ──[esptool]──> 보드
5-A:                               .bin ──[esptool]──> 보드
                                    └ 이미 v5.0.2로 빌드된 파일을 받아서 사용
```

| | 5-A. 완성본 굽기 | 5-B. 직접 빌드 |
|---|---|---|
| ESP-IDF | **불필요** | v5.0.2 필요 |
| Python | 3.10 이상 아무거나 | 3.12 권장 |
| 추가 내려받기 | **없음** (저장소에 포함) | esp-csi 소스 + ESP-IDF |
| 설치량 | 수 MB (esptool) | 수 GB, 30분+ |
| 가능한 일 | 업로드만 | 펌웨어 코드 수정·재빌드 |

**펌웨어 C 코드를 고칠 계획이 없다면 5-A를 선택하고 5-B는 건너뛴다.**

ESP-IDF는 C 소스를 `.bin`으로 만드는 컴파일러다. 5-A는 이미 컴파일된 결과물을 쓰기만 하므로 ESP-IDF도, 3.12 제약도 적용되지 않는다. 보드에 올라가는 펌웨어는 어느 쪽이든 ESP-IDF v5.0.2 기준으로 통일된다.

오히려 **5-A가 팀 전체의 펌웨어를 바이트 단위로 동일하게 만든다.** 재현 빌드가 비활성이라 각자 5-B로 빌드하면 기능은 같아도 바이너리는 서로 달라지지만, 5-A는 같은 파일을 복사하기 때문이다.

### 5-A. 미리 빌드된 바이너리로 업로드 (권장)

완성 바이너리는 **저장소에 포함되어 있다.** 클론했다면 이미 갖고 있으므로 따로 받을 것이 없다.

```text
firmware/prebuilt/
├─ tx/  bootloader.bin, partition-table.bin, csi_send.bin
└─ rx/  bootloader.bin, partition-table.bin, ota_data_initial.bin, console_test.bin
```

**TX는 3개, RX는 4개이며 오프셋이 서로 다르다.**

| 보드 | 오프셋 | 파일 |
|---|---|---|
| TX (2MB) | `0x0` | `firmware/prebuilt/tx/bootloader.bin` |
| | `0x8000` | `firmware/prebuilt/tx/partition-table.bin` |
| | `0x10000` | `firmware/prebuilt/tx/csi_send.bin` |
| RX (4MB) | `0x0` | `firmware/prebuilt/rx/bootloader.bin` |
| | `0x8000` | `firmware/prebuilt/rx/partition-table.bin` |
| | `0x1d000` | `firmware/prebuilt/rx/ota_data_initial.bin` |
| | `0x20000` | `firmware/prebuilt/rx/console_test.bin` |

빌드 출처와 SHA-256은 [firmware/prebuilt/README.md](../firmware/prebuilt/README.md)에 있다. 이 바이너리에는 프로젝트 패치가 적용되어 있어 채널 전환 명령이 포함되고 기본 채널이 `6`이다.

esptool을 설치한다.

```powershell
.\.venv\Scripts\python.exe -m pip install esptool
```

아래 명령은 **프로젝트 루트에서** 실행한다. 포트는 4장에서 확인한 실제 번호로 바꾼다.

TX 보드에 업로드한다. flash size는 2MB다.

```powershell
.\.venv\Scripts\python.exe -m esptool --chip esp32s3 -p COM7 -b 460800 write_flash `
  --flash_mode dio --flash_freq 80m --flash_size 2MB `
  0x0 firmware\prebuilt\tx\bootloader.bin `
  0x8000 firmware\prebuilt\tx\partition-table.bin `
  0x10000 firmware\prebuilt\tx\csi_send.bin
```

RX 보드에 업로드한다. flash size는 4MB이고 앱 오프셋이 `0x20000`이다.

```powershell
.\.venv\Scripts\python.exe -m esptool --chip esp32s3 -p COM8 -b 460800 write_flash `
  --flash_mode dio --flash_freq 80m --flash_size 4MB `
  0x0 firmware\prebuilt\rx\bootloader.bin `
  0x8000 firmware\prebuilt\rx\partition-table.bin `
  0x1d000 firmware\prebuilt\rx\ota_data_initial.bin `
  0x20000 firmware\prebuilt\rx\console_test.bin
```

**TX와 RX의 펌웨어를 바꿔 굽지 않도록 주의한다.** RX 앱을 TX와 같은 `0x10000`에 구우면 부팅되지 않는다.

업로드 후 RX의 `RST`를 한 번 누르고 6장으로 넘어간다.

### 5-B. ESP-IDF로 직접 빌드 (5-A를 했다면 건너뛴다)

> 5-A로 업로드를 마쳤다면 이 절 전체를 건너뛰고 [6장](#6-실시간-모니터-실행)으로 간다.
> 펌웨어 C 코드를 직접 수정할 때만 필요하다.

#### 5-B-1. ESP-CSI 소스 내려받기

`third_party/esp-csi/`는 저장소에 포함되지 않는다. 클론 직후에는 없으므로 직접 받아야 한다.

```powershell
.\scripts\fetch-esp-csi.ps1
```

`versions.json`의 고정 커밋 `740083e5ac0067b8e5ba812d2d08fd94f8ce0348`을 체크아웃하고 `firmware/patches/esp-csi-project.patch`를 적용한다. 인터넷 연결이 필요하다.

스크립트가 패치 적용 여부를 스스로 검증한다. 정상이면 다음 중 하나가 출력되고 종료 코드는 `0`이다.

```text
프로젝트 ESP-CSI 패치를 적용했습니다.
esp-csi가 이미 준비되어 있습니다(패치 적용 확인): ...
```

패치를 적용할 수 없으면 복구 방법과 함께 오류로 중단된다. 이 경우 안내대로 `third_party\esp-csi`를 지우고 다시 실행한다. 체크아웃된 커밋이 `versions.json`과 다르면 경고가 출력된다.

#### 5-B-2. ESP-IDF v5.0.2 설치

공식 설치 절차로 ESP-IDF **v5.0.2**를 설치한다. 다른 버전은 이 프로젝트의 기준이 아니다.

#### 5-B-3. 설치 경로 확인

`scripts/activate-idf.ps1`은 기본 설치 경로를 자동으로 사용한다.

```text
Python : %LOCALAPPDATA%\Programs\Python\Python312
ESP-IDF: %USERPROFILE%\esp\esp-idf-v5.0.2
도구    : %USERPROFILE%\.espressif
```

기본 위치에 설치했다면 수정할 것이 없다. 다른 곳에 설치했다면 스크립트를 고치지 말고 환경 변수로 지정한다.

```powershell
$env:CSI_PYTHON312_PATH = 'D:\Python312'
$env:IDF_PATH = 'D:\esp\esp-idf-v5.0.2'
$env:IDF_TOOLS_PATH = 'D:\.espressif'
```

경로가 틀리면 스크립트가 찾지 못한 경로와 지정 방법을 함께 출력하고 중단한다.

#### 5-B-4. 활성화 확인

```powershell
. .\scripts\activate-idf.ps1
& "$env:IDF_PYTHON_ENV_PATH\Scripts\python.exe" "$env:IDF_PATH\tools\idf.py" --version
```

`ESP-IDF v5.0.2`가 나와야 한다. Windows에서 `idf.py --version`만 실행하면 ESP-IDF가 아니라 `idf-exe` 래퍼 버전 `v1.0.3`이 표시될 수 있다.

#### 5-B-5. 빌드와 업로드

모니터와 수집기를 모두 닫고 포트를 다시 확인한 뒤 실행한다.

```powershell
.\scripts\build-firmware.ps1
.\scripts\flash-sender.ps1 -Port COM7
.\scripts\flash-receiver.ps1 -Port COM8
```

TX는 `csi_send`, RX는 `console_test` 펌웨어다. 펌웨어 변경과 재빌드는 사용자 승인 후 진행한다.

#### 5-B-6. firmware/prebuilt 갱신

펌웨어 C 코드를 바꿔서 다시 빌드했다면, 팀이 5-A로 받는 바이너리도 함께 갱신한다. 그러지 않으면 다른 사람은 옛 펌웨어를 계속 굽게 된다.

갱신 대상과 절차는 [firmware/prebuilt/README.md](../firmware/prebuilt/README.md)에 있다. 파일 7개를 교체하고 그 문서의 출처·SHA-256도 새 값으로 바꾼다.

### 빌드 결과 해시는 사람마다 다르다 (5-B만 해당)

[개발 환경 문서](environment.md)에 펌웨어 SHA-256이 기록돼 있지만, **직접 빌드한 바이너리의 해시는 반드시 달라진다.** `CONFIG_APP_REPRODUCIBLE_BUILD`가 비활성이라 빌드 시각과 경로가 바이너리에 포함되기 때문이다. 해시가 다르다고 해서 환경이 잘못된 것이 아니다. 동일성은 커밋(`versions.json`)과 패치 적용 여부로 판단한다.

## 6. 실시간 모니터 실행

```powershell
.\scripts\start-radar-monitor.ps1 -Port COM8
```

정상이면 Radar 값과 링크 상태가 표시된다. 데이터 수집:

```powershell
.\scripts\collect.ps1 -Port COM8 -Label empty_room -Duration 60
```

모니터, 공식 GUI, 수집기, `idf.py monitor`는 같은 COM 포트를 동시에 사용할 수 없다.

## 7. 새 보드용 공간 프로필 만들기

저장소에는 공간 프로필과 수집 데이터가 포함되지 않는다. 처음 실행하면 비어 있는 `기본 공간` 프로필만 만들어지므로, 자신의 환경 값을 직접 채워야 한다.

1. 모니터에서 `새 프로필 추가`를 누른다.
2. 공간 이름, TX-RX 배치 설명, 직선거리(m)를 입력한다.
3. `채널 + 공간 통합 보정 (약 100초)`으로 채널 선택과 빈 공간 보정을 연속 실행한다.
4. 완료 창에서 선택 채널과 프로필 저장 결과를 확인한다.
5. 30초 정지에서 `STATIC`, 이후 움직임에서 `MOVEMENT DETECTED`가 뜨는지 확인한다.

자세한 절차는 [사용법의 빈 공간 보정](usage.md#4-빈-공간-보정)과 [공간 프로필](usage.md#41-공간-프로필-저장과-복원)을 참고한다.

### 프로필의 보드 MAC

새 프로필의 `devices.txMac`/`rxMac`은 처음에 `null`이다. 보드 MAC은 환경마다 다르므로 임의의 기본값을 넣지 않는다.

- **RX MAC**: 보드가 부팅할 때 `wifi:mode : sta (...)` 로그가 나오면 모니터가 자동으로 기록한다. 이미 실행 중인 보드에 모니터를 붙이면 이 로그가 없으므로, 모니터를 켠 뒤 RX의 `RST`를 한 번 누르면 채워진다.
- **TX MAC**: RX 시리얼로는 관측할 수 없다. 필요하면 TX를 PC에 연결해 부팅 로그에서 확인한 뒤 프로필 JSON에 직접 적는다.

한 번 기록된 MAC은 자동으로 덮어쓰지 않는다. 보드를 교체했다면 새 프로필을 만든다.

## 8. 자주 막히는 지점

| 증상 | 원인과 조치 |
|---|---|
| `이 시스템에서 스크립트를 실행할 수 없습니다` | 현재 창에서 `Set-ExecutionPolicy -Scope Process Bypass` 실행 |
| `MSYS Python은 ... 실행하지 못합니다` | python.org 배포판 Python(3.10 이상) 설치 후 `bootstrap.ps1` 재실행 |
| `Python 3.10 이상을 찾지 못했습니다` | python.org에서 설치하고 `Add python.exe to PATH` 체크 |
| `ports`에 RX가 안 보임 | `UART` 단자에 연결했는지, USB-UART 드라이버가 잡혔는지 확인 |
| 포트는 보이는데 Radar 데이터가 전혀 없음 | **새 보드라면 5장 펌웨어 업로드를 안 한 것.** 업로드 후 다시 확인 |
| RX 보드가 부팅 안 됨 / 무한 재부팅 | 앱 오프셋 확인. RX는 `0x20000`, TX는 `0x10000` |
| 글자가 깨져서 나옴 | RX는 `2000000` baud. `idf.py monitor`는 기본값이 다를 수 있음 |
| COM 포트를 열 수 없음 | 모니터·GUI·수집기·`idf.py monitor` 중 하나가 이미 포트를 쓰는 중 |
| `third_party\esp-csi` 폴더가 없음 | 정상. `.\scripts\fetch-esp-csi.ps1` 실행 |
| 채널 전환이 안 되고 기본 채널이 11 | 패치 미적용. `third_party\esp-csi` 삭제 후 `fetch-esp-csi.ps1` 재실행 |
| `ESP-IDF v5.0.2가 없습니다` | 5-B-3의 경로 수정 |
| 정지 중에도 계속 `MOVEMENT DETECTED` | 최종 배치에서 빈 공간 보정 재실행 |

## 9. 다음 단계

세팅이 끝나면 [사용법](usage.md)의 매일 시작 순서, 빈 공간 보정, 공간 프로필과 행동 수집 절차를 따른다. 새 PC/새 방/새 보드는 기존 프로필을 그대로 쓰지 말고 별도 프로필로 관리한다.
