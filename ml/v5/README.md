# v5: ESP-Fi raw CSI 2D CNN baseline

ESP-Fi HAR의 `950 x 52` amplitude를 통계 특징으로 축약하지 않고 2D CNN에 직접 입력한다. 첫 비교 모델은 `Simple CSI-CNN`과 `CSI-ResNet18`이다.

## 고정된 실험 조건

- 목표 라벨: `fall`, `walking`, `other_motion`
- 원본 7개 행동 모두 사용: fall과 walk를 제외한 5개 행동은 other_motion
- 참가자 분리: train=1~5, validation=6, test=7~8
- 샘플 수: train 1,400 / validation 280 / test 560
- 정규화: 샘플별·서브캐리어별 z-score
- 학습 증강: amplitude scale, 작은 Gaussian noise, 시간 이동
- 손실: class-weighted cross entropy
- 선택 지표: validation macro-F1
- 최종 보고: macro-F1, balanced accuracy, fall precision/recall/F1, walking F1, confusion matrix
- seed: 42

Test 참가자는 체크포인트 선택에 사용하지 않는다. `--protocol environment`를 지정하면 train=환경 1~2, validation=환경 3, test=환경 4로 별도 실험할 수 있다.

## 실습실 PC 준비

1. NVIDIA 드라이버와 Python 3.11 64-bit를 설치한다.
2. 저장소와 `ESP-Fi-HAR-full` 원본을 복사한다. 다음 경로 아래 `.mat` 파일이 정확히 2,240개여야 한다.

```text
csi-monitor/ml/dataset/raw/ESP-Fi-HAR-full/
```

3. `csi-monitor\ml\v5`에서 다음 배치 파일을 실행한다.

```bat
setup-lab.bat
run-smoke-test.bat
run-baselines.bat
```

`setup-lab.bat`의 기본 PyTorch wheel index는 CUDA 12.6(`cu126`)이다. 실습실 드라이버 또는 PyTorch 공식 설치 선택기가 다른 index를 요구하면 첫 번째 인수로 전달한다.

```bat
setup-lab.bat https://download.pytorch.org/whl/cu128
```

최신 설치 명령은 [PyTorch 공식 설치 선택기](https://pytorch.org/get-started/locally/)를 우선한다. PowerShell 실행 정책과 무관하도록 `.bat`로 제공했다.

## 직접 실행

```bat
.venv\Scripts\python.exe check_environment.py --require-cuda
.venv\Scripts\python.exe -m unittest -v test_v5.py
.venv\Scripts\python.exe train.py --model simple_cnn --require-cuda
.venv\Scripts\python.exe train.py --model resnet18 --require-cuda
```

GPU 메모리가 부족하면 `--batch-size 8`, 여유가 있으면 `--batch-size 32`를 사용한다. 기본값은 16이다. 결과는 `output/<model>-<protocol>-<timestamp>/` 아래 저장된다.

```text
best.pt               best validation checkpoint
config.json           실행 환경과 hyperparameter
history.csv            epoch별 train/validation 지표
summary.json           최종 validation/test 지표
confusion_matrix.csv   test confusion matrix
```

두 학습이 끝나면 `compare_results.py`가 `output/baseline_comparison.csv`를 만들고 핵심 지표를 화면에 표시한다.

첫 결과를 확인하기 전에는 epoch, augmentation, learning rate를 모델별로 다르게 조정하지 않는다. 동일 조건 비교가 끝난 후에만 튜닝한다.
