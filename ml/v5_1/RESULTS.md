# v5.1 공개 CSI CNN 4-fold 교차검증 결과

실행일: 2026-08-16

## 한눈에 보는 결론

세 공개 CSI 데이터셋과 세 CNN의 모든 조합을 4-fold로 평가해 **총 36회 GPU
학습을 완료했다.** 모든 조합의 `folds`는 4이고 실패 또는 NaN fold는 없다.

데이터셋별 test macro-F1 최고 모델은 다음과 같다.

| 데이터셋 | 최고 모델 | Macro-F1 평균 ± 표준편차 | 핵심 판단 |
|---|---|---:|---|
| ESP-Fi HAR | **EfficientNet-B0** | **90.75% ± 1.22%** | 낙상 recall 86.87%, 낙상 F1 83.52% |
| UT-HAR | **CSI-ResNet18** | **92.66% ± 1.96%** | 낙상 recall 82.43%, 낙상 F1 83.20% |
| CSI-HAR-3room | **Simple CSI-CNN** | **90.11% ± 5.36%** | walking recall 92.47%, walking F1 91.43% |

실시간 시스템의 입력 계약은 ESP-Fi와 같은 `950 x 52`이므로 현재 시스템용
후보는 **EfficientNet-B0**로 정한다. ResNet18보다 ESP-Fi macro-F1이 2.86%p
높고 fold 표준편차도 3.40%p 낮았다. 이 모델은 `ml/v_main/`의 안정 경로에서
관리한다.

## 실험 구성

- 데이터셋: ESP-Fi HAR, UT-HAR, CSI-HAR-3room
- 모델: Simple CSI-CNN, CSI-ResNet18, EfficientNet-B0
- 교차검증: 각 데이터셋/모델 조합당 4 folds
- 총 학습: 3 datasets × 3 models × 4 folds = 36회
- 최대 epoch: 60
- early-stopping patience: 10
- batch size: 16
- learning rate: 0.001
- weight decay: 0.0001
- dropout: 0.3
- seed: 42
- 정규화: 샘플별·서브캐리어별 z-score
- 증강: amplitude scaling, 작은 Gaussian noise, 시간 이동
- 손실: class-weighted cross entropy
- checkpoint 선택: validation macro-F1
- GPU: NVIDIA GeForce RTX 3060 12GB
- 드라이버: 595.95
- Python: 3.14.3
- PyTorch: 2.13.0+cu126
- CUDA build: 12.6
- 정식 학습 시간: 약 1시간 51분 28초

GPU 메모리 부족은 발생하지 않았으며 batch size를 낮추지 않았다.

## 데이터와 fold

| 데이터셋 | 입력 | 클래스 | fold 방식 |
|---|---|---|---|
| ESP-Fi | `950 x 52` | fall / walking / other_motion | 참가자 pair grouped 4-fold |
| UT-HAR | `250 x 90` | fall / walking / other_motion | 공식 train+val stratified 4-fold |
| CSI-HAR | `250 x 114` | walking / other_motion | session grouped 4-fold |

- ESP-Fi: 4개 환경, 8명, 2,240개
- UT-HAR: 공식 train+validation 4,473개로 CV, 공식 test 500개는 잠금 유지
- CSI-HAR: 3개 방, 10개 세션, 227개 window

CSI-HAR에는 fall이 없으므로 2분류 점수를 다른 두 3분류 데이터셋과 직접
비교하지 않는다. UT-HAR 처리본에는 참가자·공간 metadata가 없어 참가자 독립
성능으로 해석하지 않는다.

## 전체 Macro-F1 결과

표준편차는 네 test fold의 population standard deviation이다.

| 데이터셋 | 모델 | folds | Test Macro-F1 | Balanced accuracy |
|---|---|---:|---:|---:|
| ESP-Fi | Simple CSI-CNN | 4 | 78.50% ± 3.55% | 79.46% ± 2.83% |
| ESP-Fi | CSI-ResNet18 | 4 | 87.89% ± 4.62% | 87.42% ± 5.89% |
| ESP-Fi | **EfficientNet-B0** | 4 | **90.75% ± 1.22%** | **92.35% ± 2.88%** |
| UT-HAR | Simple CSI-CNN | 4 | 84.28% ± 3.19% | 87.05% ± 1.48% |
| UT-HAR | **CSI-ResNet18** | 4 | **92.66% ± 1.96%** | **92.59% ± 1.66%** |
| UT-HAR | EfficientNet-B0 | 4 | 89.76% ± 1.64% | 90.15% ± 1.76% |
| CSI-HAR | **Simple CSI-CNN** | 4 | **90.11% ± 5.36%** | **91.30% ± 3.91%** |
| CSI-HAR | CSI-ResNet18 | 4 | 88.42% ± 1.69% | 88.65% ± 2.22% |
| CSI-HAR | EfficientNet-B0 | 4 | 84.14% ± 7.87% | 84.62% ± 8.27% |

## ESP-Fi와 UT-HAR 낙상 결과

| 데이터셋 | 모델 | Fall recall | Fall F1 | Walking F1 |
|---|---|---:|---:|---:|
| ESP-Fi | Simple CSI-CNN | 54.06% ± 11.50% | 55.21% ± 9.84% | 90.82% ± 2.91% |
| ESP-Fi | CSI-ResNet18 | 72.50% ± 18.20% | 77.15% ± 13.94% | 91.68% ± 2.12% |
| ESP-Fi | **EfficientNet-B0** | **86.87% ± 10.06%** | **83.52% ± 5.50%** | **93.19% ± 2.74%** |
| UT-HAR | Simple CSI-CNN | 76.37% ± 2.41% | 67.84% ± 5.16% | 93.54% ± 2.02% |
| UT-HAR | **CSI-ResNet18** | **82.43% ± 3.71%** | **83.20% ± 4.29%** | **97.97% ± 0.86%** |
| UT-HAR | EfficientNet-B0 | 77.65% ± 5.02% | 76.65% ± 4.12% | 97.21% ± 0.66% |

ESP-Fi에서는 모델 규모가 커질수록 낙상과 전체 성능이 함께 개선됐다.
EfficientNet-B0은 Simple CNN보다 낙상 recall이 32.81%p, 낙상 F1이 28.31%p
높았다. UT-HAR에서는 ResNet18이 세 지표 모두 가장 높아 데이터셋에 따라 최적
backbone이 달랐다.

## CSI-HAR walking 결과

| 모델 | Walking recall | Walking F1 | Other-motion F1 |
|---|---:|---:|---:|
| **Simple CSI-CNN** | 92.47% ± 11.73% | **91.43% ± 5.22%** | **88.79% ± 6.01%** |
| CSI-ResNet18 | **97.22% ± 4.81%** | 90.44% ± 3.91% | 86.41% ± 1.88% |
| EfficientNet-B0 | 92.73% ± 5.54% | 88.63% ± 2.35% | 79.65% ± 13.88% |

Simple CNN이 macro-F1과 두 클래스 F1은 가장 높았고, ResNet18은 walking recall과
fold 안정성이 더 높았다. CSI-HAR는 227개 window뿐이므로 단일 최고 점수보다
표준편차와 세션 차이를 함께 봐야 한다.

## 최고 모델의 최악 fold와 주요 혼동

### ESP-Fi EfficientNet-B0: fold 1

- macro-F1: 88.69%
- fall recall: 71.25%
- fall F1: 74.03%
- 주요 혼동: fall 80개 중 23개를 other_motion으로 누락
- 주요 오탐: other_motion 400개 중 17개를 fall로 판단

| 실제 / 예측 | fall | walking | other_motion |
|---|---:|---:|---:|
| fall | 57 | 0 | 23 |
| walking | 0 | 79 | 1 |
| other_motion | 17 | 3 | 380 |

### UT-HAR ResNet18: fold 3

- macro-F1: 89.52%
- fall recall: 77.00%
- fall F1: 76.24%
- 주요 혼동: fall 100개 중 18개를 other_motion으로 누락
- 주요 오탐: other_motion 689개 중 25개를 fall로 판단

| 실제 / 예측 | fall | walking | other_motion |
|---|---:|---:|---:|
| fall | 77 | 5 | 18 |
| walking | 0 | 326 | 3 |
| other_motion | 25 | 14 | 650 |

### CSI-HAR Simple CNN: fold 2

- macro-F1: 81.94%
- walking recall: 72.22%
- walking F1: 83.87%
- 주요 혼동: walking 36개 중 10개를 other_motion으로 판단

| 실제 / 예측 | walking | other_motion |
|---|---:|---:|
| walking | 26 | 10 |
| other_motion | 0 | 20 |

36개 전체에서 가장 낮은 fold는 CSI-HAR EfficientNet-B0 fold 4의 macro-F1
71.59%였다. 작은 session-grouped 데이터에서 EfficientNet의 fold 편차가 큰 것이
주된 원인이다.

## 실행 중 발견하고 수정한 문제

1. `scripts/bootstrap.ps1`이 권장 Python 3.12가 없을 때 설치된 다음 Python
   후보로 넘어가지 못했다. 후보별 실행 실패를 건너뛰도록 수정했다.
2. 최종 집계 CSV가 3분류의 fall 지표와 CSI-HAR의 walking 지표를 동시에 쓸 때
   서로 다른 열 때문에 실패했다. 모든 행의 열 합집합을 사용하도록 수정하고
   회귀 테스트를 추가했다.

두 문제 모두 학습 설정이나 fold 결과를 변경하지 않았다. 집계 오류 후 재실행할
때 36개 `summary.json`을 모두 인식해 재학습 없이 건너뛰었다.

## 완료 검증

- dataset/model 조합: 9개
- 조합별 folds: 모두 4
- fold 디렉터리: 36개
- fold별 `best.pt`, `history.csv`, `confusion_matrix.csv`, `summary.json`: 모두 존재
- `output/cross_validation/cv_summary.csv`: 생성 완료
- NaN 또는 infinity: 0건
- v5.1 테스트: 3개 통과
- gateway 테스트: 43개 통과
- smoke test: checkpoint 포함 필수 파일 생성 확인

## 최종 선택과 다음 단계

현재 ESP32 실시간 입력과 같은 ESP-Fi 기준으로 **EfficientNet-B0을 다음 모델로
선택한다.** `ml/v_main/`에는 이 구조의 검증된 checkpoint와 입력·출력 계약을
함께 유지한다.

다음 검증 우선순위는 다음과 같다.

1. ESP-Fi 환경 grouped 4-fold로 공간 일반화 확인
2. CSI-HAR room 3-fold로 방 일반화 확인
3. 자체 ESP32-S3 데이터로 scratch와 public pretraining fine-tuning 비교
4. 최종 checkpoint의 10/20/30Hz inference latency 및 장시간 오경보 측정
5. locked 자체 test를 통과한 checkpoint로 `ml/v_main/model.pt` 교체

현재 공개 데이터 checkpoint는 시스템 통합 후보이며 자체 ESP32-S3와 실제 주거
공간에 대한 최종 안전성 검증을 대신하지 않는다.
