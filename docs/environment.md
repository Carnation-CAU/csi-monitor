# ESP32-S3 Wi-Fi CSI 개발 환경

최종 확인일: 2026-08-04

이 문서는 프로젝트의 기준 환경을 기록하는 문서다. 설치 경로와 측정 결과는
사용자마다 다르므로, 각자 자신의 환경에서 확인한 값을 기준으로 삼는다. 프로그램 사용 순서는 [사용법](usage.md)을 참고한다.

## 문서 동기화 규칙

- 언어·라이브러리·ESP-IDF·ESP-CSI 버전이 바뀌면 이 문서를 같은 변경에서 수정한다.
- 설치 경로, 환경 변수, 하드웨어 역할, 포트 규칙 또는 아키텍처가 바뀌면 이 문서를 수정한다.
- 실행 명령, UI, 보정·수집 절차가 바뀌면 [사용법](usage.md)을 수정한다.
- 한 변경이 환경과 사용 흐름에 모두 영향을 주면 두 문서를 함께 수정한다.
- 코드·설정 변경은 사용자 승인 후 진행하며, 승인된 변경에 필요한 문서 동기화는 해당 작업에 포함한다.

## 1. 시스템 구성

```text
ESP32-S3 TX
  └─ ESP-NOW 기반 2.4 GHz Wi-Fi 패킷 송신
             ↓
        공간의 전파 변화
             ↓
ESP32-S3 RX
  └─ CSI 수집 및 Espressif Radar 값 계산
             ↓ UART, 2,000,000 baud
Windows PC
  ├─ Python 실시간 움직임 모니터
  ├─ 원본 직렬 데이터 저장
  └─ 향후 전처리·학습·서버 전송
```

현재 TX-RX 실험에는 공유기나 인터넷이 필요하지 않다. TX가 ESP-NOW 패킷을 보내고 RX가 해당 패킷의 CSI를 분석한다.

## 2. 공식 코드와 프로젝트 코드의 경계

### Espressif 공식 구성

- 저장소: `third_party/esp-csi`
- TX 펌웨어: `examples/get-started/csi_send`
- RX 펌웨어: `examples/esp-radar/console_test`
- 움직임 값과 `move/static` 판정: RX의 Espressif Radar 펌웨어
- 빈 공간 보정 명령: `radar --train_start`, `radar --train_stop`

ESP32 펌웨어의 핵심 C 감지 코드는 현재 수정하지 않았다.

### 프로젝트에서 추가한 구성

- `gateway/src/csi_gateway`: 직렬 포트 검색, JSONL 수집기, 간단한 실시간 모니터
- `scripts/start-radar-monitor.ps1`: 프로젝트 모니터 실행
- `scripts/collect.ps1`: 데이터 수집
- `docs`: 환경, 사용법과 실험 문서

프로젝트 모니터는 감지 모델을 새로 구현한 것이 아니라 RX 공식 펌웨어의 `RADAR_DADA` 출력과 공식 보정 명령을 사용한다.

### 공식 PC GUI 변경 이력

`third_party/esp-csi/examples/esp-radar/console_test/tools/esp_csi_tool.py`에는 현재 Python 환경과의 호환을 위해 다음 변경이 들어가 있다.

- Radar 그래프 축 자동 확대
- 실제로 수집된 표본만 시간축에 표시
- pandas 3.x에서 CSV 파일 객체를 유지하도록 초기화 방식 수정

공식 GUI의 첫 결과 이후 갱신 중단 문제가 완전히 해소되지 않아 일상적인 확인에는 프로젝트 모니터를 사용한다.

## 3. 고정 버전

| 항목 | 현재 값 |
|---|---|
| ESP-IDF | `v5.0.2` |
| ESP-IDF 경로 (기본값) | `%USERPROFILE%\esp\esp-idf-v5.0.2` |
| ESP-IDF 도구 경로 (기본값) | `%USERPROFILE%\.espressif` |
| ESP-CSI 커밋 | `740083e5ac0067b8e5ba812d2d08fd94f8ce0348` |
| Python | `3.12` 검증됨 (최소 `3.10`) |
| Python 가상환경 | `.venv` |
| 펌웨어 대상 | `esp32s3` |
| RX 직렬 속도 | `2,000,000 baud` |
| TX/RX Wi-Fi 채널 | 런타임 `1`, `6`, `11`; 재시작 시 기본값 `6` |
| TX Wi-Fi 채널 폭 | `HT40 (40 MHz)` 시험 설정 |
| TX 설정 송신 빈도 | `100 Hz` |

기준값은 루트의 `versions.json`에도 기록한다.

예비 시험에서 HT20보다 HT40의 Radar 결과와 패킷 연속성이 좋았고, 채널 1·6·11
비교에서는 환경에 따라 선택이 달라졌다. 따라서 특정 채널을 고정 권장값으로 두지
않고, 각 설치 환경에서 GUI의 자동 채널 비교로 결정한다. 보드 재시작 시 기본
채널은 `6`이다.

개발용 자동 채널 비교와 PC 공간 프로필 저장은 GUI에 구현했으며, 보드 자체의
NVS 영구 저장과 장애 자동 복구는 아직 구현하지 않았다.

빈 공간 보정값은 RX 런타임 값이다. RX 재시작, 펌웨어 업로드, 채널 변경 또는
배치 변경 후에는 다시 보정해야 한다. 링크 품질과 보정 결과는 방 구조, 가구,
TX-RX 거리와 높이에 따라 달라지므로 다른 환경의 수치를 그대로 기대하지 않는다.

## 4. Windows 환경

### 주요 경로

아래는 기본 설치 경로다. 실제 경로는 PC마다 다르며, `activate-idf.ps1`이
환경 변수로 덮어쓸 수 있게 되어 있다.

```text
프로젝트: 임의의 경로 (한글·공백 없는 경로 권장)
Python: %LOCALAPPDATA%\Programs\Python\Python312
ESP-IDF: %USERPROFILE%\esp\esp-idf-v5.0.2
ESP-IDF tools: %USERPROFILE%\.espressif
IDF Python: %USERPROFILE%\.espressif\python_env\idf5.0_py3.12_env
```

기본값과 다른 곳에 설치했다면 다음 환경 변수로 지정한다.

```powershell
$env:CSI_PYTHON312_PATH = 'D:\Python312'
$env:IDF_PATH = 'D:\esp\esp-idf-v5.0.2'
$env:IDF_TOOLS_PATH = 'D:\.espressif'
```

### Python 의존성

프로젝트 `.venv`에는 다음 주요 패키지가 설치되어 있다.

- pyserial
- PyQt5
- PyQtGraph
- NumPy
- pandas
- SciPy
- path

공식 GUI는 오래된 코드를 사용하지만 현재 환경은 Python 3.12 및 pandas 3.x 계열이므로 호환 제약이 있다.

### Python 버전

`pyproject.toml`의 요구 사항은 `>=3.10`이며 검증된 버전은 `3.12`다. 3.13과
3.14도 PC 게이트웨이(수집·모니터) 의존성 wheel이 모두 제공되므로 설치는 가능하다.
다만 ESP-IDF v5.0.2는 3.12까지를 기준으로 구성했으므로, **펌웨어를 빌드한다면
3.12를 사용한다.** `bootstrap.ps1`은 3.12가 있으면 우선 사용하고 없으면 3.13,
3.14 순으로 진행한다.

### ESP-IDF 활성화

```powershell
. .\scripts\activate-idf.ps1
```

스크립트는 `IDF_TOOLS_PATH`가 설정돼 있지 않으면 `%USERPROFILE%\.espressif`로 지정한다.

실제 ESP-IDF 버전 확인:

```powershell
& "$env:IDF_PYTHON_ENV_PATH\Scripts\python.exe" `
  "$env:IDF_PATH\tools\idf.py" --version
```

예상 출력:

```text
ESP-IDF v5.0.2
```

Windows에서 `idf.py --version`만 실행하면 ESP-IDF가 아니라 `idf-exe` 래퍼 버전 `v1.0.3`이 표시될 수 있다.

## 5. 하드웨어 환경

검증된 구성은 ESP32-S3 revision 0.2, embedded PSRAM 8 MB 보드 2대다.

| 역할 | 포트 예시 | USB 인터페이스 |
|---|---|---|
| TX 송신기 | `COM7` | Espressif USB Serial/JTAG |
| RX 수신기 | `COM8` | CH343 UART |

COM 번호는 PC와 USB 단자마다 다르므로 `python -m csi_gateway ports`로 확인한다.
보드 MAC은 환경마다 다르며 공간 프로필의 `devices`에 기록된다. RX MAC은 부팅
로그가 관측되면 모니터가 자동으로 채운다.

RX 데이터 포트의 식별 기준:

```text
USB-Enhanced-SERIAL CH343
VID:PID=1A86:55D3
```

`VID:PID=303A:1001`인 Espressif native USB 포트는 현재 프로젝트 모니터가 사용하는 RX UART 포트가 아니다.

## 6. 프로젝트 구조

```text
startup-competition/
├─ gateway/src/csi_gateway/   PC 수집기와 모니터
├─ gateway/tests/             Python 테스트
├─ scripts/                   Windows/macOS 실행 스크립트
├─ third_party/esp-csi/       고정된 Espressif 공식 저장소
├─ data/raw/                  원본 JSONL 데이터
├─ data/manifests/            수집 세션 메타데이터
├─ data/profiles/             공간별 배치·채널·보정값과 세션 연결
├─ data/datasets/             가져온 팀 데이터셋 라이브러리
├─ data/exports/              팀 공유용 데이터셋 ZIP 출력
├─ docs/environment.md        현재 환경 기준
└─ docs/usage.md              실제 사용 절차
```

## 7. 확인된 펌웨어 빌드

두 펌웨어 모두 `esp32s3` 대상으로 빌드됐다.

| 펌웨어 | 용도 | 크기 | SHA-256 |
|---|---|---:|---|
| `csi_send.bin` | TX | 685,600 bytes | `9039F1F1F27148FBBD52625E23C59AA771404AA0F7B60A9295E3BC1A2C18A6DA` |
| `console_test.bin` | RX | 825,904 bytes | `174AD1E24FB1A275CE7F877C7F20D00437A7690574AF3764D52BF3D83A5C9B1C` |

**이 해시는 재현되지 않는다.** 두 프로젝트 모두 `CONFIG_APP_REPRODUCIBLE_BUILD`가 비활성이므로 빌드 시각과 빌드 경로가 바이너리에 포함된다. 같은 커밋과 같은 패치로 다시 빌드해도 해시는 달라진다. 위 값은 2026-08-04 빌드의 기록이며, 다른 환경에서 대조할 검증 기준이 아니다.

환경 동일성은 다음으로 판단한다.

- `versions.json`의 ESP-CSI 커밋과 ESP-IDF 버전
- `firmware/patches/esp-csi-project.patch` 적용 여부
- 플래시 오프셋: TX 앱 `0x10000` / RX 앱 `0x20000`(+ `0x1d000` OTA 데이터)

## 8. 현재 검증 상태

예비 환경에서 다음까지 확인했다. 수치는 환경마다 다르므로 각자 재확인한다.

- TX-RX 패킷 송수신 및 RX CSI 출력 확인
- RX UART `2,000,000 baud` 확인
- 움직임 구간의 평균 jitter가 정지 구간보다 뚜렷하게 높음
- 프로젝트 모니터에서 Radar 값, 링크 상태와 빈 공간 보정 명령 지원
- Python 자동 테스트 41개 통과
- `rf_channel` 명령으로 채널 `1`/`6`/`11` 동기 전환 및 복귀 확인

## 8.1 개발용 자동 채널 비교 확장

사용자 승인에 따라 Espressif 예제에 다음 프로젝트 전용 기능만 추가했다.

- TX: RX가 보내는 채널 전환 제어 패킷 수신
- RX: `rf_channel` 조회 및 `rf_channel --set 1|6|11` 동기 전환 명령
- GUI: 현재 Wi-Fi 채널과 HT40 표시
- GUI: 채널 1·6·11의 링크 품질 자동 비교, 최종 채널 선택과 빈 공간 보정 연속 실행

Espressif의 CSI 수집, Radar waveform 계산, `move/static` 판정식과 빈 공간
학습 알고리즘은 수정하지 않았다. 런타임 채널은 RAM 상태이며 두 보드가
재시작되면 채널 6으로 돌아간다.

자동 비교의 선택 정책은 평균 속도와 RSSI보다 **연속성과 최저 패킷률을 먼저**
평가한다. 예비 시험에서는 평균 Hz가 더 높은 채널이라도 최저값이 낮으면 선택되지
않았다. 선택 결과는 환경마다 다르므로 설치할 때마다 실행한다.

보정 후 정지·걷기·눕기와 누운 상태의 움직임이 GUI에서 구분되는 것까지 확인했다.
다음 검증 단계는 행동별 반복 수집과 정답 시각 기록이다.

현재 결과는 한 배치에서 파이프라인이 작동한다는 기술 검증이다. 여러 환경의 정확도, 사람 존재 감지, 낙상 감지와 서비스 수준 성능은 아직 검증되지 않았다.

## 8.2 공간 프로필과 안내형 수집 확장

사용자 승인에 따라 프로젝트 모니터에 다음 기능을 추가했다. Espressif의
Radar 계산식과 움직임 판정 코드는 변경하지 않았다.

- 드롭다운으로 여러 공간 프로필 선택
- 이름, 배치 설명과 TX-RX 거리를 입력하는 새 프로필 추가
- 공간 이름, 배치 설명, 거리와 TX/RX 위치·높이를 수정하는 프로필 편집
- 물리 배치 정보 수정 시 기존 보정값 자동 무효화
- 선택 프로필 삭제 시 복구용 보관 폴더로 이동
- 프로필이 없을 때 만드는 빈 `기본 공간` 프로필
- 배치 설명, TX-RX 거리, 채널, 대역폭, 장치 MAC 저장
- 빈 공간 보정 완료 시 공식 펌웨어가 출력한 존재·움직임 임계값 저장
- `공간 프로필 적용`으로 채널과 저장된 공식 Radar 설정을 RX에 다시 적용
- 수집 전 예정 행동은 선택 사항이며 종료 후 실제 행동을 정답으로 확정하는 안내형 수집
- 시작 1회·중간 신호 2회·정상 종료 3회의 구분 알림음
- 매트리스 모의 낙상 수집 전 별도 안전 확인과 manifest 기록
- 종료 라벨 취소·안전 미확인 낙상은 원본만 보존하고 학습에서 자동 제외
- 유효한 행동 세션만 대상으로 Radar 시계열 특징 CSV 생성
- 기존 세션을 기준으로 새 수집 세션의 가장 가까운 행동을 표시하는 실험용 예측
- 원본 JSONL, manifest와 한글 요약 자동 생성
- 각 수집 세션을 사용 중인 공간 프로필에 자동 연결
- 팀 ESP-Radar 데이터셋 ZIP 내보내기·체크섬 검증 가져오기
- 가져온 데이터셋을 공간 프로필의 참고 행동 데이터로 연결·해제
- 공간별 공식 임계값 대비 상대 `wander/jitter` 특징으로 참고 행동 비교
- 현재 보정 이후의 로컬 빈방·정지 재실 세션이 분리될 때만 상대 `wander` 기반 PC 보조 판정 활성화
- 정지 재실 기준 부족·겹침 시 공식 `someone` 판정으로 자동 폴백

GUI에서 선택한 프로필이 현재 작업 대상이다. 선택 상태에서 통합 보정을 실행하면
채널 비교가 성공한 뒤 선택 채널에서 빈 공간 보정이 자동으로 이어지고, 채널과
새 임계값을 같은 프로필에 함께 저장한다. 행동 수집도 같은
프로필의 `profileId`와 `roomId`를 manifest에 기록한다.

프로필 파일은 `data/profiles/<profileId>.json`이다. 프로필이 하나도 없으면
`default-space.json`(`기본 공간`)이 생성되며 배치·거리·보정값·MAC이 모두 비어
있다. 실제 배치를 입력하고 통합 보정을 한 번 완료하면 그때부터 값이 채워진다.

수집 데이터와 공간 프로필은 개인 환경 정보를 담으므로 저장소에 올리지 않는다
(`.gitignore` 참고). 각자 자신의 PC에서 생성해 사용한다.

GUI에서 삭제한 프로필은 원본 데이터와 함께 제거되지 않는다. 프로필 JSON만
`data/profiles/archive`로 이동하며 드롭다운 목록에서 제외된다. 마지막 남은
프로필은 삭제할 수 없다.

공간 프로필 복원은 물리적 배치를 자동으로 복원하지 않는다. TX/RX의 위치,
높이, 안테나 방향, 주요 가구와 문 상태가 크게 달라지면 같은 프로필이어도
다시 보정하거나 별도 프로필을 만들어야 한다.

## 9. 환경 변경 시 원칙

### 같은 집에서 계속 사용하는 경우

- TX와 RX 위치, 높이와 방향을 고정한다.
- RX를 재시작했거나 정지 오탐이 반복되면 빈 공간 보정을 다시 한다.
- 큰 가구나 문 상태가 바뀌어 결과가 달라지면 새 배치 조건으로 다시 검증한다.

### 다른 집 또는 방으로 옮기는 경우

1. 포트와 링크 품질 확인
2. TX-RX 배치 기록
3. 빈 공간 보정
4. 정지와 걷기 확인
5. 해당 환경을 별도 세션으로 수집

보정값은 RX에서는 런타임 값이지만 PC의 공간 프로필에 저장할 수 있다. 같은
배치를 물리적으로 복원한 뒤 `공간 프로필 적용`을 누르면 채널과 보정값을
다시 적용한다. 새로운 방이나 배치는 기존 데이터와 섞지 말고 별도 프로필로
관리해야 한다.

## 10. macOS 이식 조건

Python 패키지와 JSONL 데이터 형식은 Windows와 macOS에서 동일하게 유지한다.

- Windows `COM8`은 macOS에서 `/dev/cu.*` 포트로 바뀐다.
- 모니터는 `python -m csi_gateway monitor`로 실행할 수 있다.
- 펌웨어를 macOS에서 다시 빌드하려면 ESP-IDF v5.0.2를 별도로 설치한다.
- ESP-CSI는 동일한 고정 커밋을 사용한다.

## 11. 환경 복구

Python 3.10 이상이 설치된 Windows에서 프로젝트 폴더로 이동한 뒤:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap.ps1
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s gateway\tests -v
```

펌웨어 빌드 및 업로드 방법은 [사용법](usage.md#8-펌웨어-빌드와-업로드)을 참고한다.
