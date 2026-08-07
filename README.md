# ESP32-S3 Wi-Fi CSI 안전 모니터링

Wi-Fi CSI로 사람의 움직임을 감지하고 낙상 의심 상황을 알리는 것을 목표로 하는 프로젝트다.
Windows와 macOS에서 동일한 데이터·분석 코드를 사용한다.

```text
ESP32-S3 송신기 → ESP32-S3 CSI 수신기 → PC 수집기
→ 움직임 감지 → 낙상 의심 이벤트 → 서버 → Android 알림
```

## 현재 포함된 것

- Windows/macOS 공용 Python CSI 직렬 수집기와 실시간 모니터
- 버전이 지정된 JSON Lines 원본 저장 형식과 세션 manifest
- 공간 프로필(배치·채널·보정값) 저장과 복원
- 채널 1·6·11 자동 비교와 빈 공간 보정
- 행동 라벨 안내형 수집과 특징 CSV 생성
- ESP-IDF 없이 업로드 가능한 완성 펌웨어 (`firmware/prebuilt`)
- Espressif `esp-csi` 고정 커밋과 프로젝트 패치

## 시작하기

새 PC에서 처음 세팅한다면 아래 문서를 순서대로 따라간다. 클론부터 보드 확인까지 전체를 다룬다.

- [Windows 초기 세팅](docs/setup-windows.md)
- [macOS 초기 세팅](docs/setup-macos.md)

```bash
git clone https://github.com/Carnation-CAU/csi-monitor.git
cd csi-monitor
```

Python은 3.10 이상이면 동작한다. 펌웨어를 직접 빌드할 때만 3.12를 권장한다.

그 밖의 절차는 [개발 환경](docs/environment.md), [사용법](docs/usage.md),
[실험 규약](docs/experiment-protocol.md), [성장 및 추가 개발 로드맵](docs/growth-roadmap.md)을 참고한다.

## 펌웨어

- 송신기(TX): `csi_send`
- 수신기(RX): `console_test`

완성 바이너리는 [`firmware/prebuilt`](firmware/prebuilt/README.md)에 포함되어 있어 ESP-IDF 없이 업로드할 수 있다.
소스를 직접 빌드하려면 `scripts/fetch-esp-csi.sh`(또는 `.ps1`)로 고정 커밋을 내려받는다.

## 데이터 취급

수집 데이터(`data/raw`, `data/manifests`, `data/processed`)와 공간 프로필(`data/profiles`)은
방 배치·보드 MAC·생활 패턴 같은 개인 환경 정보를 담으므로 저장소에 올리지 않는다.
각자 자신의 PC에서 생성해 사용한다.

## 안전 및 표현 원칙

- 시스템 출력은 `낙상`이 아니라 `낙상 의심(FALL_SUSPECTED)`으로 표현한다.
- 고령자에게 모의 낙상을 수행하게 하지 않는다.
- 원본 CSI는 수정하지 않고 파생 데이터는 별도 버전으로 생성한다.
- 실제 사람/세션 단위로 학습·검증·테스트를 분리한다.

---

# 🔥 Project Convention

## 🛠️ Build Info
- **Language** : Python 3.10+ (검증 3.12), C (ESP32-S3 펌웨어)
- **Framework** : PyQt5 / PyQtGraph (GUI), ESP-IDF v5.0.2 (펌웨어)
- **Data Store** : JSON Lines 파일 기반 (`data/`), 별도 DB 없음

## 🪾 Branching Rule
- 기본적으로 `develop`에서 checkout 하기
  1. checkout 전에 반드시 `pull` 하기!!!
  2. merge가 늦어져서 불가피하게 checkout해야 되는 경우, merge도 checkout한 브랜치로!
     1. ex. `feat/#1`에서 `feat/#2`를 체크아웃한 경우, `feat/#2`의 PR base는 `feat/#1`
  3. 잘 모르겠으면 파트장에게 물어보기

## 📋 Branch Name Convention
브랜치의 이름은 다음과 같은 규칙을 따릅니다.

| type       | name                | description               |
|------------|---------------------|---------------------------|
| `feat`     | `feat/#ISSUE_NUM`     | ⚡️ 새로운 기능 추가            |
| `fix`      | `fix/#ISSUE_NUM`      | 🐛 버그 수정                 |
| `docs`     | `docs/#ISSUE_NUM`     | 📝 문서 수정                 |
| `refactor` | `refactor/#ISSUE_NUM` | 💫 리팩토링                  |
| `test`     | `test/#ISSUE_NUM`     | 🧪 테스트 코드 작성            |
| `chore`    | `chore/#ISSUE_NUM`    | 🛠️ 빌드, 패키지 관련 수정       |
| `perf`     | `perf/#ISSUE_NUM`     | 🪄 성능 개선                 |
| `ci`       | `ci/#ISSUE_NUM`       | 🔄 CI 관련 수정              |
| `cd`       | `cd/#ISSUE_NUM`       | 🔄 CD 관련 수정              |
| `revert`   | `revert/#ISSUE_NUM`   | ⚠️ 특정 커밋으로 되돌리기         |
| `hotfix`   | `hotfix/#ISSUE_NUM`   | 🔥 배포된 사항 중 시급히 수정 필요한 것 |
| `docker`   | `docker/#ISSUE_NUM`   | 🐳 Docker 작업             |

이후, 이 브랜치에서 작업하는 내용을 누구나 알 수 있도록 명시합니다.
완성 예시 : `feat/#1-login-api`

## ⚠️ Issue Convention
이슈 제목은 **타입**과 간단한 **설명**을 적습니다.

ex. `[Feat] 상품 CRUD 구현`

## 📄 Commit Convention
- 최소 작업 단위로 가능한 한 **작게 쪼개어 커밋**합니다.
- 하나의 커밋에는 하나의 작업만 포함합니다.
- 커밋 메시지 제목은 작업 내용을 직관적으로 이해하기 쉽게 작성합니다.

커밋 메시지 구조는 다음과 같습니다.

```text
feat: 상품 조회 기능 구현
fix: 상품 조회 중, 잘못된 ID인 경우 예외를 던지도록 수정
```

커밋 `Prefix`의 경우, 브랜치 네이밍 타입과 동일한 방식으로 작성합니다.

## 📌 Git Branch Strategy
| branch    | role                                            |
|-----------|-------------------------------------------------|
| `main`    | - 최종 배포용 브랜치<br>- develop 브랜치에서 안정화 버전만 병합 |
| `develop` | - 개발용 브랜치<br>- 시니어에게 리뷰 진행 후 병합             |
