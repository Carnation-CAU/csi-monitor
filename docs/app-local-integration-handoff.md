# Carnation 앱 로컬 연동 인수인계

최종 확인일: 2026-08-11

## 1. 목표

초기 MVP에서는 별도 백엔드를 인터넷에 배포하지 않는다. ESP32 RX가 연결된
Windows PC 또는 MacBook에서 Python CSI 게이트웨이와 로컬 API를 함께 실행하고,
같은 Wi-Fi에 연결된 Android 앱이 이 API에서 실시간 상태와 낙상 의심 이벤트를
받는다.

```text
ESP32 TX/RX
  → USB 직렬
Python CSI 게이트웨이 + 로컬 API
  → 같은 Wi-Fi의 REST/WebSocket
Carnation Android 앱
```

ESP32 펌웨어는 서버에 배포하지 않는다. 보드에 플래시한 뒤 현장에서 동작한다.
Android 앱도 개발 중에는 Play Store에 배포하지 않고 Android Studio에서 실제
스마트폰에 디버그 설치한다.

## 2. 확인된 앱 상태

앱 저장소: `C:\Users\ww\Desktop\carnation-app`

- Kotlin, Jetpack Compose, Android SDK 35, JDK 17
- `FallEvent` JSON 계약과 검증 구현 완료
- 목업 이벤트 목록·상세·보호자 확인 화면 구현 완료
- `AssetsFallEventSource`에서 목업 JSON을 읽는 상태
- `FallEventRepository.confirm()`은 로컬 메모리만 변경
- FCM 파서와 알림 표시 뼈대는 있으나 Firebase SDK는 아직 미적용
- 실제 REST, WebSocket, 영구 저장과 서버 확인 응답은 미구현

앱에서 교체할 핵심 위치:

- `data/FallEventSource.kt`: 목업 소스를 REST 구현으로 교체
- `data/FallEventRepository.kt`: 실시간 이벤트 추가와 확인 결과 POST
- `push/FCM_SETUP.md`: 실제 FCM을 붙일 때 사용
- `model/FallEvent.kt`: 기존 낙상 이벤트 계약 유지

## 3. 배포 없이 가능한 두 가지 시험 수준

### 수준 A: 완전 로컬 시험

- 게이트웨이 PC와 앱 스마트폰을 같은 Wi-Fi에 연결한다.
- 앱이 `http://<게이트웨이-PC-IP>:8000`에 접속한다.
- 화면이 열려 있을 때 WebSocket으로 상태 변경을 즉시 수신한다.
- 인터넷과 서버 배포가 없어도 된다.

제약: Android 절전 정책 때문에 앱이 종료되거나 장시간 백그라운드에 있으면
WebSocket 알림을 보장할 수 없다. 초기 기능 시험용이다.

### 수준 B: 서버 배포 없이 백그라운드 알림 시험

- 상태 조회와 이벤트 저장은 수준 A와 동일하게 로컬에서 처리한다.
- 로컬 Python 프로세스가 인터넷을 통해 FCM에 낙상 알림을 발송한다.
- Firebase 서비스 계정 키는 PC에만 보관한다.
- Android 앱은 FCM을 수신한다.

이 구성은 자체 백엔드 배포는 필요 없지만 Firebase 프로젝트와 인터넷 연결은
필요하다. FCM 서버 자격 증명을 Android 앱이나 ESP32에 포함하면 안 된다.

## 4. 핫스팟 시험 조건

권장 구성:

```text
핫스팟 제공 장치 1대
  ├─ 게이트웨이 PC 연결
  └─ Carnation 앱 시험 스마트폰 연결
```

핫스팟을 제공하는 스마트폰 자체에서 앱도 실행하면 제조사와 Android 버전에
따라 테더링 클라이언트인 PC로 접속하지 못할 수 있다. 가능하면 핫스팟 제공
장치와 앱 시험 스마트폰을 분리한다. 공유기나 휴대용 라우터를 써도 구조는 같다.

게이트웨이 PC에서 확인할 항목:

1. `ipconfig` 또는 `ifconfig`로 같은 Wi-Fi 대역의 IP 확인
2. 로컬 API를 `127.0.0.1`이 아니라 `0.0.0.0`에 바인딩
3. Windows 방화벽에서 선택한 TCP 포트를 개인 네트워크에 허용
4. 스마트폰 브라우저에서 `http://<PC-IP>:8000/health` 확인

`python -m csi_gateway serve` 명령과 API 서버는 아직 구현 전이다. 명령을 먼저
실행하지 말고 CSI 저장소에서 로컬 API 구현이 완료된 뒤 사용한다.

## 5. 데이터 계약

### 5.1 실시간 상태

낙상 이벤트와 현재 상태를 분리한다.

```json
{
  "schema_version": "1.0",
  "device_id": "home-001-rx",
  "profile_id": "bedroom-center",
  "observed_at": "2026-08-11T23:10:00+09:00",
  "presence_state": "present_resting",
  "presence_probability": 0.78,
  "presence_reason": "resting_state_held",
  "movement_state": "static",
  "link_state": "active",
  "rssi": -67,
  "packet_hz": 83,
  "channel": 1
}
```

초기 상태 후보:

- `present_active`: 움직이는 사람이 감지됨
- `present_resting`: 이전 재실이 확인됐고 휴식·수면 가능성이 있음
- `possibly_absent`: 퇴실과 유사한 변화 후 빈방 기준선이 유지됨
- `unknown`: 링크 중단 또는 정지 사람과 빈방을 구분할 근거 부족

추가 하드웨어 없이 `possibly_absent`를 확정 부재로 표현하지 않는다.

### 5.2 낙상 의심 이벤트

앱에 이미 구현된 `FallEvent` v1.0 계약을 유지한다.

```json
{
  "schema_version": "1.0",
  "event_type": "fall_suspected",
  "window_id": "bedroom-center:1528",
  "detected_at": "2026-08-11T23:10:00+09:00",
  "room_id": "bedroom-center",
  "risk_score": 0.82,
  "evidence": {
    "motion_label": "fall_like",
    "motion_confidence": 0.84,
    "presence_state": "present",
    "presence_probability": 0.78,
    "no_recovery_sec": 12.0
  }
}
```

### 5.3 보호자 확인

```json
{
  "window_id": "bedroom-center:1528",
  "confirmation": "normal",
  "confirmed_at": "2026-08-11T23:11:20+09:00"
}
```

`confirmation` 후보는 `normal`, `help_needed`다.

## 6. 예정 API

아래 경로는 양쪽 팀이 구현 전에 합의할 계약이다.

| 방식 | 경로 | 용도 |
|---|---|---|
| `GET` | `/health` | 로컬 연결 확인 |
| `GET` | `/api/v1/status` | 최신 재실·움직임·링크 상태 |
| `GET` | `/api/v1/events` | 낙상 의심 이벤트 목록 |
| `WS` | `/api/v1/stream` | 상태 변경과 새 이벤트 실시간 수신 |
| `POST` | `/api/v1/events/{window_id}/confirmation` | 정상·도움 필요 응답 |

연결이 끊기면 앱은 지수 백오프로 WebSocket을 다시 연결하고, 재연결 직후
`GET /api/v1/status`와 `GET /api/v1/events`로 누락 상태를 동기화한다.

## 7. Android 담당 작업

1. `INTERNET` 권한 추가
2. 디버그 빌드에서만 로컬 HTTP 허용 또는 로컬 HTTPS 구성
3. API 기본 주소를 소스에 고정하지 않고 `BuildConfig`로 분리
4. `AssetsFallEventSource`와 병행 가능한 `HttpFallEventSource` 구현
5. 실시간 `HomeStatus` 모델과 화면 상태 추가
6. WebSocket 재연결과 REST 재동기화 구현
7. `FallEventRepository.confirm()`에서 확인 결과 POST
8. 앱 재시작 후에도 이벤트를 유지하도록 Room 또는 DataStore 추가
9. 수준 B 시험 시 Firebase Messaging 연결

실시간 상태는 REST/WebSocket으로 받고 FCM은 낙상·장치 오프라인 같은 중요한
알림에만 사용한다. 초당 상태값을 FCM으로 전송하지 않는다.

## 8. CSI 담당 작업

1. GUI 상태와 독립된 최신 상태 저장소 구성
2. 로컬 REST/WebSocket API 구현
3. `HomeStatus` 직렬화와 스키마 검증
4. 낙상 의심 이벤트 생성과 중복 방지
5. 보호자 확인 결과 로컬 저장
6. 연결 종료 후 재접속을 위한 이벤트 이력 제공
7. 수준 B 시험 시 로컬 FCM 발송 모듈 추가

Espressif 공식 Radar 계산식과 펌웨어 감지 로직은 별도 승인 없이 수정하지 않는다.

## 9. 10초 데이터 사용 원칙

10초 데이터를 반복하거나 시간축으로 늘인 데이터는 다음 용도로만 사용한다.

- 앱↔게이트웨이 통신 시험
- 상태 전이 타이머 시험
- 그래프와 화면 장시간 표시 시험
- 저장 공간과 재연결 부하 시험

학습·정확도 검증에서는 하나의 10초 구간을 여러 표본으로 세지 않는다. 반복한
데이터를 학습과 테스트에 나누면 같은 파형을 외운 결과가 정확도로 나타난다.
시간축 확대는 호흡과 움직임의 주파수 특성도 바꾼다.

현재 MVP는 각 상태 10초로 전체 파이프라인을 먼저 확인할 수 있다. 이후에는
한 번의 30분보다 서로 다른 시간과 자세에서 독립적으로 기록한 10초 구간을
여러 개 모으는 것이 낫다. 실제 수면 재실 성능을 주장하기 전에는 실제 장시간
데이터로 별도 검증해야 한다.

## 10. 로컬 통합 완료 기준

- 스마트폰 브라우저에서 게이트웨이 `/health` 접근
- 앱에서 최신 `HomeStatus` 표시
- 움직임 후 앱 상태가 2초 안에 갱신
- 새 `FallEvent`가 목록에 중복 없이 추가
- 앱의 `정상`·`도움 필요` 결과가 게이트웨이에 저장
- Wi-Fi를 껐다 켠 뒤 앱이 자동 재연결하고 누락 이벤트 동기화
- 수준 B에서는 앱이 백그라운드일 때 FCM 낙상 의심 알림 수신
