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
- 팀 ESP-Radar 데이터셋 내보내기·가져오기와 프로필 참고 연결
- 채널 1·6·11 자동 비교 후 선택 채널에서 이어지는 빈 공간 통합 보정
- 공식 `someone`·`moving`과 공간 전용 상대 `wander` 기준을 이용한 실험용 재실·부재 상태 안정화
- 종료 후 실제 행동을 확정하는 안내형 수집과 특징 CSV 생성
- 평상시 움직임·정지 전이와 낙상 의심 이벤트의 날짜별 자동 기록
- 충격성 변화 후 8초간 회복 움직임이 없을 때 앱 서버로 낙상 의심 이벤트 전송
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
[실험 규약](docs/experiment-protocol.md), [ML 학습·시스템 적용 계획](docs/ml-system-integration-plan.md),
[성장 및 추가 개발 로드맵](docs/growth-roadmap.md)을 참고한다.

## 펌웨어

- 송신기(TX): `csi_send`
- 수신기(RX): `console_test`

완성 바이너리는 [`firmware/prebuilt`](firmware/prebuilt/README.md)에 포함되어 있어 ESP-IDF 없이 업로드할 수 있다.
소스를 직접 빌드하려면 `scripts/fetch-esp-csi.sh`(또는 `.ps1`)로 고정 커밋을 내려받는다.

## 데이터 취급

수집·자동 감지 데이터(`data/raw`, `data/manifests`, `data/processed`, `data/events`), 공간 프로필(`data/profiles`)과
가져온·내보낸 데이터셋(`data/datasets`, `data/exports`)은
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
- 기본적으로 `main`에서 checkout 하기
  1. checkout 전에 반드시 `pull` 하기!!!
  2. merge가 늦어져서 불가피하게 checkout해야 되는 경우, merge도 checkout한 브랜치로!
     1. ex. `feat/#1`에서 `feat/#2`를 체크아웃한 경우, `feat/#2`의 PR base는 `feat/#1`
  3. 잘 모르겠으면 파트장에게 물어보기

이 저장소는 배포 대상이 없으므로 통합용 `develop` 브랜치를 두지 않는다.
작업 브랜치를 `main`에서 분기하고 PR로 다시 `main`에 병합한다.

## 📋 Branch Name Convention
브랜치의 이름은 다음과 같은 규칙을 따릅니다.

| type       | name                  | description                |
|------------|-----------------------|----------------------------|
| `feat`     | `feat/#ISSUE_NUM`     | ⚡️ 새로운 기능 추가             |
| `fix`      | `fix/#ISSUE_NUM`      | 🐛 버그 수정                  |
| `exp`      | `exp/#ISSUE_NUM`      | 🔬 측정·분석 실험               |
| `docs`     | `docs/#ISSUE_NUM`     | 📝 문서 수정                  |
| `refactor` | `refactor/#ISSUE_NUM` | 💫 리팩토링                   |
| `test`     | `test/#ISSUE_NUM`     | 🧪 테스트 코드 작성             |
| `chore`    | `chore/#ISSUE_NUM`    | 🛠️ 빌드, 패키지, 스크립트 관련 수정 |

이후, 이 브랜치에서 작업하는 내용을 누구나 알 수 있도록 명시합니다.
완성 예시 : `feat/#1-space-profile-save`

### `exp` 브랜치는 병합하지 않아도 됩니다
채널 비교, 배치 변경, 임계값 조정처럼 **결과를 확인하는 것이 목적인 작업**에 사용합니다.
코드가 남을 필요는 없고, 결론만 `docs/` 문서로 정리해 별도 PR로 병합합니다.
`feat`와 섞으면 병합되지 않은 브랜치의 이유를 알 수 없게 되므로 구분합니다.

## ⚠️ Issue Convention
이슈 제목은 **타입**과 간단한 **설명**을 적습니다.

ex. `[Feat] 공간 프로필 저장·복원 구현`
ex. `[Exp] 채널 1·6·11 링크 품질 비교`

## 📄 Commit Convention
- 최소 작업 단위로 가능한 한 **작게 쪼개어 커밋**합니다.
- 하나의 커밋에는 하나의 작업만 포함합니다.
- 커밋 메시지 제목은 작업 내용을 직관적으로 이해하기 쉽게 작성합니다.

커밋 메시지 구조는 다음과 같습니다.

```text
feat: 공간 프로필에 보정 임계값 저장 기능 구현
fix: RX 부팅 로그가 없을 때 프로필 MAC이 비지 않도록 수정
```

커밋 `Prefix`의 경우, 브랜치 네이밍 타입과 동일한 방식으로 작성합니다.

## 📌 Git Branch Strategy
| branch              | role                                                                     |
|---------------------|--------------------------------------------------------------------------|
| `main`              | - 기준 브랜치<br>- setup 문서대로 따라가면 동작하는 상태를 항상 유지<br>- 작업 브랜치에서 리뷰 후 병합 |
| `feat/#1-...` 등 | - 각자 작업 브랜치<br>- `main`에서 분기해 `main`으로 PR                             |

배포 단계가 생기면(서버·Android 데모) 그때 `develop`을 도입한다.
그전까지는 `main` 하나만 유지한다.
