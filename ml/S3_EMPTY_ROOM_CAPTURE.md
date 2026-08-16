# ESP32-S3 빈방 CSI 데이터 수집 요청

## 목적

ESP-Fi의 ESP32-C3 데이터와 실제 ESP32-S3 입력의 시간축·주파수축을 맞추기 위한 기초 데이터 수집입니다.

낙상이나 행동 데이터는 필요하지 않습니다. **빈방 CSI만 2~5분 저장**하면 됩니다.

## 권장 설정

- 장치: ESP32-S3 송신기·수신기
- Wi-Fi 채널: 6 고정
- 대역폭: HT20 권장
- CSI 종류: LLTF
- 송신률: 100Hz
- Serial baud rate: 2,000,000
- 송수신기 위치와 안테나 방향 고정

HT20이나 LLTF 설정이 어렵다면 임의로 추측하지 말고, 실제 사용한 설정을 함께 알려주세요.

## 수집 환경

1. 송신기와 수신기를 실제 사용할 위치에 설치합니다.
2. 통신이 안정된 후 10초 정도 기다립니다.
3. 방에서 사람이 모두 나갑니다.
4. 문, 선풍기, 커튼처럼 움직일 수 있는 물체를 멈춥니다.
5. 2~5분 동안 데이터를 저장합니다.
6. 수집 중에는 보드나 안테나를 움직이지 않습니다.

## 수집 명령

프로젝트 루트에서 PowerShell을 실행합니다.

```powershell
$env:PYTHONPATH = ".\gateway\src"

.\.venv\Scripts\python.exe -m csi_gateway.cli collect `
  --port COM7 `
  --baud 2000000 `
  --duration 300 `
  --label empty_room `
  --room-id room-01 `
  --device-id rx-s3-001 `
  --project-root .
```

`COM7`은 실제 ESP32-S3 수신기 포트로 변경합니다.

`.venv`가 없다면 프로젝트의 환경 설정을 먼저 실행해야 합니다.

## 반드시 저장되어야 하는 정보

Serial에서 들어오는 `CSI_DATA` 원문 전체를 그대로 저장해야 합니다.

가능하면 다음 정보가 포함되어야 합니다.

- sequence
- device timestamp
- host timestamp
- 전체 raw I/Q 배열
- raw CSI 길이
- LTF 종류
- HT20/HT40
- primary/secondary channel
- `first_word_invalid`
- RSSI
- noise floor
- FFT gain
- AGC gain
- STBC 및 signal mode

52개 amplitude만 별도로 계산해서 보내지 말고, **원본 `CSI_DATA` 문자열이 포함된 JSONL을 보내주세요.**

## 생성되는 파일

수집이 끝나면 다음 두 파일이 생성됩니다.

```text
data/raw/<session-id>.jsonl
data/manifests/<session-id>.json
```

두 파일을 ZIP으로 압축해서 전달해주세요.

추가로 다음 정보도 함께 적어주세요.

```text
보드 모델:
사용한 COM 포트:
Wi-Fi 채널:
대역폭:
LTF:
송신률:
펌웨어 버전 또는 Git commit:
ESP-IDF 버전:
실제 수집 시간:
수집 중 사람의 움직임 여부:
```

## 수집 성공 확인

JSONL 파일을 텍스트 편집기로 열었을 때 다음과 같은 원문이 반복해서 보여야 합니다.

```text
CSI_DATA,...
```

파일에 `RADAR_DATA`만 있고 `CSI_DATA`가 없다면 CSI 원본이 저장되지 않은 것이므로 알려주세요.

## 주의사항

- JSONL을 Excel로 열어서 다시 저장하지 마세요.
- 원본 파일을 수정하거나 정규화하지 마세요.
- `data/raw`는 GitHub에 올리지 마세요.
- 낙상 동작은 수행할 필요가 없습니다.
- 수집 설정을 정확히 모르면 추측하지 말고 실제 상태를 기록해주세요.
