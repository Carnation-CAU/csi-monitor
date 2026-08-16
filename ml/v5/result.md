# v5 Raw CSI 2D CNN 학습 결과

실행일: 2026-08-16

## 한눈에 보는 결론

ESP-Fi HAR의 원본 `950 x 52` CSI amplitude를 직접 입력하는 두 2D CNN을
같은 조건으로 학습했다. **CSI-ResNet18이 최종 test macro-F1 93.94%로
Simple CSI-CNN의 81.52%보다 12.42%p 높았다.**

두 모델 모두 test 낙상 80개 중 77개를 찾아 낙상 recall은 96.25%로 같았다.
그러나 Simple CSI-CNN은 `other_motion` 400개 중 77개를 낙상으로 잘못
분류한 반면, CSI-ResNet18은 이를 9개로 줄였다. 그 결과 낙상 precision은
50.00%에서 89.53%, 낙상 F1은 65.81%에서 92.77%로 크게 개선됐다.

따라서 현재 참가자 분리 기준의 v5 baseline으로는 **CSI-ResNet18을 채택**한다.
다만 환경 분리 실험은 아직 수행하지 않았으므로 새로운 공간에 대한 일반화
성능으로 해석해서는 안 된다.

## 실험 구성

- 데이터: ESP-Fi HAR 4개 환경, 8명, 7개 행동, 총 2,240개
- 입력: 샘플별 `950 x 52` CSI amplitude
- 목표 라벨: `fall`, `walking`, `other_motion`
- `other_motion`: run, turn, jump, squat, arm wave
- 참가자 분리: train 1~5, validation 6, test 7~8
- 샘플 수: train 1,400 / validation 280 / test 560
- 정규화: 샘플별·서브캐리어별 z-score
- 학습 증강: amplitude scale, Gaussian noise, 시간 이동
- 손실 함수: class-weighted cross entropy
- 모델 선택 지표: validation macro-F1
- 최대 epoch: 60, early-stopping patience: 10
- batch size: 16
- learning rate: 0.001
- weight decay: 0.0001
- dropout: 0.3
- random seed: 42
- 실행 장치: NVIDIA GeForce RTX 3060 12GB, CUDA 12.6
- 실행 환경: Python 3.11.9, PyTorch 2.13.0+cu126

test 참가자 데이터는 체크포인트 선택에 사용하지 않고, validation 참가자의
macro-F1이 가장 높은 checkpoint를 고른 뒤 최종 평가에 한 번 사용했다.

## 모델 구성

| 모델 | 파라미터 수 | 최고 validation epoch | 종료 epoch |
|---|---:|---:|---:|
| Simple CSI-CNN | 93,283 | 20 | 30 |
| CSI-ResNet18 | 11,171,779 | 21 | 31 |

두 실행 모두 validation macro-F1이 더 개선되지 않아 patience 10 조건으로 조기
종료됐다.

## 최종 test 결과

| 모델 | Accuracy | Balanced accuracy | Macro-F1 | 낙상 Precision | 낙상 Recall | 낙상 F1 | 걷기 F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Simple CSI-CNN | 83.21% | 91.17% | 81.52% | 50.00% | 96.25% | 65.81% | 91.95% |
| **CSI-ResNet18** | **95.54%** | **95.92%** | **93.94%** | **89.53%** | **96.25%** | **92.77%** | **92.22%** |

CSI-ResNet18은 Simple CSI-CNN보다 accuracy가 12.32%p, balanced accuracy가
4.75%p, macro-F1이 12.42%p 높았다. 낙상 발견률은 유지하면서 낙상 오경보를
크게 줄인 것이 가장 중요한 차이다.

## Validation 결과

| 모델 | Accuracy | Balanced accuracy | Macro-F1 | 낙상 Precision | 낙상 Recall | 낙상 F1 | 걷기 F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Simple CSI-CNN | 87.86% | 88.33% | 84.45% | 63.46% | 82.50% | 71.74% | **90.48%** |
| **CSI-ResNet18** | **94.29%** | **92.00%** | **92.00%** | **92.11%** | **87.50%** | **89.74%** | 90.24% |

모델 선택에 사용한 validation에서도 CSI-ResNet18의 macro-F1과 낙상 F1이
높았다. test에서만 우연히 순위가 뒤집힌 결과가 아니라 validation과 test가
같은 결론을 보였다.

## Test confusion matrix

행은 실제 라벨, 열은 예측 라벨이다.

### Simple CSI-CNN

| 실제 / 예측 | fall | walking | other_motion |
|---|---:|---:|---:|
| fall | **77** | 0 | 3 |
| walking | 0 | **80** | 0 |
| other_motion | **77** | 14 | **309** |

### CSI-ResNet18

| 실제 / 예측 | fall | walking | other_motion |
|---|---:|---:|---:|
| fall | **77** | 0 | 3 |
| walking | 0 | **77** | 3 |
| other_motion | **9** | 10 | **381** |

Simple CSI-CNN은 실제 낙상과 걷기 자체는 잘 찾았지만, 다양한 일상 동작을
낙상으로 과도하게 판단했다. CSI-ResNet18은 낙상 true positive 77개를 그대로
유지하면서 낙상 false positive를 77개에서 9개로 68개 줄였다. 실제 경보
시스템에서는 같은 낙상 recall에서 오경보 부담을 크게 낮추는 결과다.

## 해석과 한계

- 현재 결과는 참가자 7~8을 처음 보는 사람으로 남긴 단일 고정 분할 결과다.
- 모든 split에 네 환경이 포함되므로 새로운 환경에 대한 성능은 보여주지 않는다.
- `other_motion`은 다섯 행동을 합친 다수 클래스다. class-weighted loss로 학습했지만
  세부 행동별 오분류 원인은 별도 분석이 필요하다.
- 공개 ESP-Fi HAR의 고정 길이 샘플 결과이며, 연속 스트림의 이벤트 검출 성능이나
  자체 ESP32-S3 장비의 domain shift를 검증한 결과는 아니다.
- 두 모델의 기본 설정을 공정하게 비교한 결과이며 hyperparameter 탐색으로 얻은
  각 구조의 성능 상한은 아니다.

다음 검증 우선순위는 같은 두 모델의 환경 분리 protocol, 세부 행동별 오류 분석,
자체 ESP32-S3 데이터 fine-tuning 순서다.

## 산출물

```text
output/
├── baseline_comparison.csv
├── simple_cnn-participant-20260816-170251/
│   ├── best.pt
│   ├── config.json
│   ├── history.csv
│   ├── summary.json
│   └── confusion_matrix.csv
└── resnet18-participant-20260816-170434/
    ├── best.pt
    ├── config.json
    ├── history.csv
    ├── summary.json
    └── confusion_matrix.csv
```

`baseline_comparison.csv`에는 smoke test를 제외한 두 전체 학습 결과만 포함했다.

## 재현 방법

`csi-monitor/ml/v5`에서 다음 순서로 실행한다.

```bat
setup-lab.bat
run-smoke-test.bat
run-baselines.bat
```

개별 실행은 다음과 같다.

```bat
.venv\Scripts\python.exe -m unittest -v test_v5.py
.venv\Scripts\python.exe train.py --model simple_cnn --require-cuda
.venv\Scripts\python.exe train.py --model resnet18 --require-cuda
.venv\Scripts\python.exe compare_results.py
```

- 환경 검사: 통과
- 자동 테스트: 2개 통과
- 전체 학습: 2개 완료
- 최종 비교 행: 2개
