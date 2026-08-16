# 환경 상태

최종 확인일: 2026-08-17

## 설치 항목

- Python 3.12 (검증됨, 최소 3.10)
- 프로젝트 가상환경: `.venv`
- ESP-IDF v5.0.2로 prebuilt 생성 완료; macOS 소스 원본은 빌드 후 삭제
- ESP32-S3 도구 체인: GCC 11.2.0으로 빌드 완료; 평상시 실행에는 불필요
- ESP-CSI 커밋: `740083e5ac0067b8e5ba812d2d08fd94f8ce0348`
- GUI 의존성: PyQt5, PyQtGraph, NumPy, pandas, SciPy

## 확인된 펌웨어

| 펌웨어 | 용도 | 크기 | SHA-256 |
|---|---|---:|---|
| `csi_send.bin` | TX | 685,584바이트 | `C2C9752FBE72B466ECD4D22D1FA16D15C1B2B5BFD254506E56FE1D3590A11150` |
| `console_test.bin` | RX | 826,112바이트 | `BFCD7B5253BDE31BC6F405D517B49279124E2A1C2E91F62438AFC6B313105160` |

두 펌웨어 모두 `esp32s3` 대상으로 HT20 빌드를 확인했다. 2026-08-17 Mac에서
두 실제 보드에 업로드하고 flash write hash 검증까지 통과했다.
평상시 모니터, 수집과 prebuilt 재플래시는 `.venv`의 `esptool`만 사용하므로
ESP-IDF 소스가 없어도 된다. C 펌웨어를 다시 수정할 때만 setup 문서에 따라
ESP-IDF v5.0.2와 `third_party/esp-csi`를 다시 내려받는다.

## 하드웨어

| 역할 | 2026-08-17 macOS 검증 포트 | USB 인터페이스 |
|---|---|---|
| CSI 송신기 | `/dev/cu.usbmodem5CCD0309411` | CH343 UART (`1A86:55D3`) |
| CSI 수신기 | `/dev/cu.usbmodem5CCD0332951` | CH343 UART (`1A86:55D3`) |

COM 번호와 보드 MAC은 PC·보드마다 다르다. `python -m csi_gateway ports`로
확인한다. 검증된 구성은 ESP32-S3 리비전 0.2, 내장 PSRAM 8MB 보드 2대다.

## 현재 검증 상태

- RX UART 2,000,000 baud 통신 확인
- TX 100Hz ESP-NOW 송신과 RX CSI/Radar 수신 확인
- HT20 RX raw CSI 길이 104(52개 I/Q 쌍) 확인
- RX 장치 timestamp 약 10,000us 간격과 연속 `CSI_DATA` 출력 확인
- 채널 1·6·11 런타임 동기 전환 확인
- 전환 후 각 채널에서 Radar 결과 연속 수신 확인
- GUI 현재 채널 표시와 자동 채널 비교 확인
- 다중 공간 프로필 선택·추가·보관 삭제와 보정값 저장·적용 기능 구현
- 공간 프로필 이름·거리·배치·TX/RX 위치 수정 기능 구현
- 물리 배치 정보 변경 시 기존 보정값 자동 무효화
- 팀 ESP-Radar 데이터셋 ZIP 내보내기·검증 가져오기 구현
- 가져온 데이터셋의 공간 프로필 참조 연결·해제 구현
- 공간 간 참고 비교용 임계값 대비 상대 Radar 특징 구현
- 수집 세션의 공간 프로필 자동 연결 구현
- 종료 후 실제 행동을 확정하는 안내형 행동 데이터 수집과 한글 요약 저장 구현
- 모의 낙상과 낙상 유사 행동 라벨 및 사전 안전 확인 추가
- 행동 인식 준비용 세션 특징 추출과 CSV 생성 구현
- 행동당 기존 세션을 기준으로 한 실험용 최근접 행동 예측 구현
- 공식 `someone`·`moving`과 공간 전용 상대 `wander` 기준을 이용한 실험용 재실 상태 안정화 구현
- 재실·정지, 재실·움직임, 부재, 판단 불가를 움직임 상태와 별도로 표시
- 보정 미완료와 Radar 중단 시 재실 상태를 `UNKNOWN`으로 처리
- 현재 보정 이후의 로컬 빈방·정지 재실 데이터만 보조 기준에 사용
- 기준 데이터 부족·겹침 시 공식 `someone` 판정으로 자동 폴백
- Python 자동 테스트 69개 통과

## 5분 빈방 수집 검증

2026-08-17 세션 `20260817-013600-c6fd2f6f`을 실제 빈방에서 300초 수집했다.

| 항목 | 확인값 |
|---|---:|
| 실제 host 기록 구간 | 299.986초 |
| 전체 직렬 레코드 | 32,331개 |
| `CSI_DATA` | 29,866개 |
| Radar 레코드 | 1,204개 |
| CSI sequence 누락 | 0개 |
| raw I/Q 길이 | 전부 104 |
| `first_word_invalid` | 전부 0 |
| 장치 timestamp 중앙 간격 | 10,000us (100Hz) |
| 실제 Wi-Fi 채널 | 전 구간 1 |
| secondary channel / `cwb` | 전부 0 / 0 (HT20) |
| 평균 RSSI | -53.0dBm |
| 평균 noise floor | -98.0dBm |

원본 JSONL과 manifest는 수정하지 않았으며 Git에 포함하지 않는다. 전달용 ZIP은
`data/exports/20260817-013600-c6fd2f6f-empty-room.zip`에 생성했다.

수집 데이터와 공간 프로필은 저장소에 포함하지 않는다. 각자 자신의 환경에서
링크 확인 → 채널 + 공간 통합 보정 순으로 기준을 새로 잡는다.

실행 명령은 [macOS 사용법](usage-macos.md) 또는
[Windows 사용법](usage-windows.md)을 참고한다.
