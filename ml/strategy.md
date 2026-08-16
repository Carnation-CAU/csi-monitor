# CSI 행동 분류 전략

최종 수정일: 2026-08-16

## 1. 목표

gateway가 재실·움직임을 판단하고, ML은 `moving=true`일 때 행동을 분류한다.

```text
입력: 최근 raw CSI 950프레임 × 52 subcarrier
출력: fall_suspected / walking / other_motion / unknown
호출: 10~30Hz, 기본 20Hz
```

모델은 `ActivityModel.predict(window)` 뒤에 숨겨 교체해도 시스템을 수정하지 않는다.

## 2. 현재 위치

- v5.1 공개 데이터 3종 × CNN 3종 × 4-fold, 총 36회 학습 완료
- ESP-Fi 기준 EfficientNet-B0을 공개 데이터 통합 후보로 선정
- gateway에 950프레임 buffer와 비동기 모델 호출 구현
- 실제 모델의 이벤트·앱 알림 연결은 아직 최종 통합 전

현재 모델은 **완성 모델이 아니라 ESP32-C3 공개 데이터 사전학습 모델**이다.

## 3. 핵심 문제

ESP-Fi는 ESP32-C3, 실제 시스템은 ESP32-S3를 사용한다. 둘 다 `950 × 52`여도
RF gain, 안테나, LTF, 대역폭, subcarrier 순서, packet rate와 공간이 달라 같은
분포가 아니다.

해결 순서:

1. C3와 S3 입력을 물리적으로 정렬한다.
2. S3 데이터로 성능 하락을 측정한다.
3. fine-tuning 또는 domain adaptation으로 보완한다.

## 4. 실행 로드맵

### 1단계 — 입력 계약 확정

```text
동일 HT20·LTF·packet 설정
→ 실제 주파수 기준 52 subcarrier 선택·정렬
→ invalid word·packet gap 처리
→ 동일 시간 구간을 950프레임으로 resampling
→ gain alignment·빈방 baseline 정규화
```

학습과 실시간 추론은 반드시 같은 전처리 코드를 사용한다.

### 2단계 — S3 데이터 수집

- 클래스: fall / walking / other_motion
- fall은 매트리스 위 통제된 모의 동작만 수집
- 빈방·무라벨 장시간 CSI도 함께 수집
- 사람·방·위치·방향·날짜·장치 배치를 분산
- train/validation/test를 사람·방·세션 단위로 분리
- locked test는 학습 전에 분리하고 마지막까지 열지 않음

### 3단계 — C3→S3 비교 실험

같은 S3 locked test에서 비교한다.

| 실험 | 구성 |
|---|---|
| A | ESP-Fi 모델 그대로: zero-shot 하한 |
| B | A + 입력 정렬 전처리 |
| C | B + labeled S3 fine-tuning |
| D | B + unlabeled S3 Mean Teacher/WiTeacher |
| E | S3 데이터로 scratch 학습 |

순서는 `A → B → C → E`다. S3 라벨이 부족하고 무라벨 데이터가 충분할 때만 D를
추가한다. WiTeacher는 hardware를 정렬하는 기술이 아니므로 B 이후에 적용한다.

### 4단계 — 모델 선택

우선순위:

1. fall recall
2. 시간당 거짓 낙상 경보
3. fall F1
4. macro-F1
5. 처음 보는 사람·방의 최저 성능
6. 10·20·30Hz 지연과 장시간 안정성

목표치와 threshold는 validation에서 확정하고 locked test 결과로 다시 조정하지 않는다.

### 5단계 — 시스템 통합

```text
ESP32-S3
→ gateway: 재실·moving 판단
→ 950 × 52 ring buffer
→ ML 비동기 추론
→ 예측 안정화
→ 이벤트 기록
→ 앱 알림
```

적용 순서:

1. shadow mode: 결과만 기록
2. 비교 mode: Radar·ML·실제 라벨 비교
3. 제한 알림: 높은 신뢰도의 낙상 후보만 전송
4. 운영 후보: 장시간 검증까지 통과한 모델만 사용

ML이 실패하거나 늦으면 이전 예측을 재사용하지 않고 `unknown`을 반환한다.

## 5. 예상 문제와 한계

| 문제 | 영향 | 대응 |
|---|---|---|
| 같은 `950×52`를 같은 신호로 오해 | S3 성능 급락 | 주파수·시간·gain 계약 검증 |
| HT20/HT40·LTF·subcarrier 불일치 | 잘못된 입력 매핑 | 설정 고정, 실제 주파수 기준 정렬 |
| packet rate 차이 | 행동 속도와 window 의미 변형 | timestamp 기반 resampling |
| packet 손실·순서 오류 | 파형 왜곡과 오탐 | sequence 검사, gap mask, 불량 window 거부 |
| 사람·방·배치 변화 | 새 환경 일반화 실패 | grouped split, 다양한 S3 수집, fine-tuning |
| `moving=false` 오판 | ML이 호출되지 않아 행동 누락 | moving gate recall을 end-to-end로 별도 평가 |
| 겹치는 window의 split 누수 | 성능 과대평가 | 이벤트·세션 단위 split 고정 |
| 모의 낙상과 실제 낙상 차이 | 실제 낙상 성능 한계 | `fall_suspected`로 출력, 안전 수집·hard negative 확대 |
| 클래스 불균형 | 낙상 무시 또는 과도한 경보 | class weight, event 기준 지표, 오경보 측정 |
| softmax 확률 과신 | 틀린 결과를 높은 확률로 출력 | calibration, unknown 거부, 연속 예측 안정화 |
| 추론 지연·GPU 장애 | 오래된 판단 또는 누락 | 비동기 호출, timeout, stale 결과 폐기 |
| 모델·전처리 버전 불일치 | 재현 불가·잘못된 추론 | checksum과 `MODEL_SPEC.json` 검증 |

공개 데이터 점수는 구조 선택과 사전학습 효과만 보여준다. 자체 S3 locked test와
실제 공간 장시간 검증 없이는 서비스 정확도를 주장하지 않는다.

## 6. 버전과 산출물

- 숫자 버전 폴더: 실험 코드와 결과
- `v_main`: 현재 통합 후보의 고정 경로
- `model.pt`: Git LFS 관리
- `MODEL_SPEC.json`: 입력·출력·전처리·성능·checksum
- raw CSI와 개인정보성 metadata: Git 제외

모델 교체 시 전처리, 명세, gateway 테스트를 함께 갱신한다.

## 7. 바로 할 일

1. C3/S3의 LTF·대역폭·subcarrier·packet rate를 확인한다.
2. 공통 S3 전처리와 빈방 baseline 보정을 구현한다.
3. S3 수집 protocol과 manifest를 확정한다.
4. S3 locked test를 먼저 분리한다.
5. A·B·C·E를 실행하고 필요할 때만 D를 추가한다.
6. 우승 모델을 shadow mode로 연결한다.
7. 장시간 오경보와 지연 기준을 통과하면 `v_main`으로 승격한다.

최종 원칙: **공개 데이터 점수로 배포하지 않고, S3 locked test와 실제 운영 검증을
통과한 모델만 서비스에 사용한다.**
