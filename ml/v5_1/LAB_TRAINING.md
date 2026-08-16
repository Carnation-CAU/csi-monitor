# v5.1 실습실 PC 학습: 처음부터 끝까지

이 문서 하나만 순서대로 따르면 된다. v5.1은 다음 36회 CNN 교차검증 실험이다.

```text
ESP-Fi HAR / UT-HAR / CSI-HAR-3room
× Simple CSI-CNN / CSI-ResNet18 / EfficientNet-B0
× 4 folds
= 36 training runs
```

현재 노트북에서는 GPU 학습을 실행하지 않았다. 데이터 구조·fold 누수·Python 문법·gateway 통합 테스트만 수행했다. 실제 epoch 학습과 checkpoint 생성은 실습실 PC에서 한다.

---

## 1. 준비물

- Windows 10/11 64-bit 실습실 PC
- NVIDIA GPU와 호환 드라이버
- Python 3.12 64-bit 권장
- 이 Git 저장소
- Git에 포함되지 않는 공개 데이터셋 3개
- 원본·가상환경·checkpoint를 위한 여유 공간 최소 15GB 권장

GPU 확인:

```bat
nvidia-smi
```

GPU 이름, driver version과 memory가 출력되어야 한다.

---

## 2. Git에 포함되지 않는 데이터 복사

다음 경로는 `.gitignore`에 등록되어 GitHub에 올라가지 않는다.

```text
csi-monitor/ml/dataset/raw/**
```

따라서 현재 PC에서 실습실 PC로 아래 세 개의 **압축 해제된 폴더**를 별도로 복사한다. ZIP은 학습에 필요 없다.

```text
csi-monitor/ml/dataset/raw/
├─ ESP-Fi-HAR-full/
│  ├─ EnvironmentNo.1(corridor)/
│  │  ├─ mat/*.mat
│  │  └─ csv/*.csv
│  ├─ EnvironmentNo.2（Office）/{mat,csv}/
│  ├─ EnvironmentNo.3（boardrooms）/{mat,csv}/
│  └─ EnvironmentNo.4（laboratory）/{mat,csv}/
├─ UT-HAR/
│  └─ UT_HAR/
│     ├─ data/
│     │  ├─ X_train.csv
│     │  ├─ X_val.csv
│     │  └─ X_test.csv
│     └─ label/
│        ├─ y_train.csv
│        ├─ y_val.csv
│        └─ y_test.csv
└─ CSI-HAR-3room/
   ├─ room_1/<session>/{data.csv,label.csv,label_boxes.csv}
   ├─ room_2/<session>/...
   └─ room_3/<session>/...
```

주의: UT-HAR의 `.csv` 확장자 파일은 실제로는 NumPy binary이므로 Excel로 열거나 다시 저장하면 안 된다.

정상 데이터 기준:

| 데이터셋 | 확인 기준 |
|---|---|
| ESP-Fi | `.mat` 2,240개, 각 `950×52` |
| UT-HAR | split 파일 6개, train 3,977 / val 496 / test 500 |
| CSI-HAR | 3개 방, 연속 세션 10개 |

CSI-HAR 원본 ZIP 검증값은 512,739,259 bytes, MD5 `711e794baee5a0bdab738cc85dcd2a2f`다.

공식 출처:

- ESP-Fi HAR: <https://github.com/AutoSmartGroup/ESP-Fi-HAR>
- UT-HAR 처리본: <https://github.com/xyanchen/wifi-csi-sensing-benchmark>
- CSI-HAR-3room: <https://figshare.com/articles/dataset/14386892>

공개 원본은 Git이나 결과물 ZIP에 재포함하지 않는다. 외부 배포나 제품 학습 전에는 각 원 저자의 데이터 이용 조건을 다시 확인한다.

---

## 3. 폴더 확인

명령 프롬프트를 열고 저장소의 v5.1 폴더로 이동한다.

```bat
cd <저장소 경로>\csi-monitor\ml\v5_1
dir
```

최소한 다음 파일이 보여야 한다.

```text
LAB_TRAINING.md
setup-lab.bat
run-smoke-test.bat
run-all-cv.bat
cross_validate.py
check_environment.py
requirements.txt
```

---

## 4. 공용 Python·CUDA 환경 설치

한 번만 실행한다.

```bat
setup-lab.bat
```

이 스크립트는 `csi-monitor/.venv` 하나에 다음을 설치한다.

- 기존 gateway와 PyQt GUI
- CUDA PyTorch와 torchvision
- NumPy, SciPy, scikit-learn
- v5.1 학습 의존성

학습과 gateway가 같은 환경을 사용하므로 학습 checkpoint를 monitor에서 바로 불러올 수 있다.

기본 PyTorch wheel은 CUDA 12.6이다. 설치가 실패하거나 실습실 드라이버와 맞지 않으면 [PyTorch 공식 설치 선택기](https://pytorch.org/get-started/locally/)에서 Windows/Pip/Python과 맞는 CUDA를 선택하고 index URL을 첫 인수로 준다.

예시:

```bat
setup-lab.bat https://download.pytorch.org/whl/cu128
```

---

## 5. 환경·데이터·테스트 확인

설치 후 다음 세 명령을 실행한다.

```bat
..\..\.venv\Scripts\python.exe check_environment.py --require-cuda
..\..\.venv\Scripts\python.exe -m unittest -v test_v5_1.py
..\..\.venv\Scripts\python.exe -m unittest discover -s ..\..\gateway\tests -v
```

필수 확인:

```text
CUDA available: True
ESP-Fi MAT files: 2240
UT-HAR split files: 6
CSI-HAR sessions: 10
PASS: environment is ready
```

`test_v5_1.py`는 다음을 확인한다.

- 세 데이터셋 모두 fold 4개
- train/validation/test sample 중복 없음
- 각 fold에 필요한 클래스 존재
- 세 CNN이 `950×52`, `250×90`, `250×114` 입력을 모두 처리

gateway 테스트가 실패하면 학습 전에 먼저 해결한다.

---

## 6. 실험 정의

### ESP-Fi

```text
Fold 1 test: participant 1,2
Fold 2 test: participant 3,4
Fold 3 test: participant 5,6
Fold 4 test: participant 7,8
```

각 fold의 다음 participant pair가 validation이고 나머지 4명이 train이다. 참가자 단위로 완전히 분리된다.

### UT-HAR

공식 train+validation 4,473개를 stratified 4-fold로 나눈다. 각 outer train에서 별도 stratified validation을 만든다. 공식 test 500개는 이번 CV에서 사용하지 않고 잠근다.

처리본에 참가자·공간 metadata가 없기 때문에 UT-HAR 결과는 참가자 독립 성능으로 주장하지 않는다.

### CSI-HAR

250프레임 window 227개를 session grouped 4-fold로 나눈다. 같은 세션 window가 split을 넘지 않는다. fall이 없으므로 `walking/other_motion` 2분류다. 방이 3개이므로 공간 일반화는 v5.1 후속 room 3-fold에서 평가한다.

### 공통 설정

- sample별·subcarrier별 z-score
- amplitude scaling, 작은 Gaussian noise, 시간 이동 augmentation
- class-weighted cross entropy
- validation macro-F1 checkpoint 선택
- 최대 60 epochs, early-stopping patience 10
- batch size 16
- seed 42
- test fold는 epoch·threshold·hyperparameter 선택에 사용하지 않음

---

## 7. 1-epoch smoke test

정식 36회 전에 반드시 실행한다.

```bat
run-smoke-test.bat
```

ESP-Fi, Simple CNN, fold 1을 클래스 균형 최대 64개 sample과 1 epoch로 실행한다. 결과는 정식 결과와 섞이지 않는 다음 경로에 저장된다.

```text
ml/v5_1/output/cross_validation/smoke/
```

CUDA out-of-memory, 모델 shape, DataLoader와 checkpoint 저장 문제는 여기서 먼저 발견한다.

---

## 8. 36회 정식 학습 실행

```bat
run-all-cv.bat
```

실행 순서:

```text
ESP-Fi: 3 models × 4 folds
UT-HAR: 3 models × 4 folds
CSI-HAR: 3 models × 4 folds
```

GPU 한 대에서 순차 실행한다. 중간에 컴퓨터가 꺼지거나 명령을 중단해도 같은 명령을 다시 실행하면 된다. `summary.json`이 존재하는 완료 fold는 자동으로 건너뛴다.

특정 실험만 실행:

```bat
..\..\.venv\Scripts\python.exe cross_validate.py --datasets espfi --models resnet18 --fold 2 --require-cuda
```

가능한 dataset 이름:

```text
espfi  ut_har  csi_har
```

가능한 model 이름:

```text
simple_cnn  resnet18  efficientnet_b0
```

GPU 메모리가 부족하면 전체 실행 명령을 다음처럼 직접 실행한다.

```bat
..\..\.venv\Scripts\python.exe cross_validate.py --batch-size 8 --require-cuda
```

그래도 부족하면 batch size 4를 사용한다. batch size를 변경했으면 `RESULTS.md`에 기록한다.

---

## 9. 결과 파일

fold별:

```text
ml/v5_1/output/cross_validation/<dataset>/<model>/fold-N/
├─ best.pt
├─ history.csv
├─ confusion_matrix.csv
└─ summary.json
```

전체 요약:

```text
ml/v5_1/output/cross_validation/cv_summary.csv
ml/v5_1/RESULTS.md
```

두 파일은 매 fold 종료 후 자동 갱신된다. 정식 판단에는 `folds=4`인 행만 사용한다.

주요 지표:

1. fall recall
2. fall precision/F1
3. macro-F1
4. walking F1
5. fold 표준편차와 최악 fold

CSI-HAR의 첫 클래스는 fall이 아니라 walking이다. CSI-HAR 2분류와 나머지 3분류의 절대 점수를 직접 비교하지 않는다.

---

## 10. 현재 시스템 통합 방식

실시간 모델 계약:

```text
ActivityModel.predict(ActivityWindow[950,52]) -> ActivityPrediction
```

- 입력은 학습 ESP-Fi와 같은 최근 950프레임이다.
- gateway는 새 CSI 프레임을 한 번만 ring buffer에 추가한다.
- moving=true일 때 10~30Hz로 최근 950프레임 snapshot을 판단한다.
- 기본값은 20Hz다.
- GPU 호출은 background worker에서 실행되어 serial과 GUI를 막지 않는다.
- CNN을 교체해도 gateway 호출·반환 형식은 바뀌지 않는다.
- 같은 서버에서는 WebSocket 없이 Python 직접 호출한다.
- 나중에 프로세스나 서버를 분리할 때만 같은 계약에 WebSocket adapter를 붙인다.

모델을 지정하지 않은 기존 실행:

```powershell
cd <저장소 경로>\csi-monitor
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-radar-monitor.ps1 -Port COM7
```

학습된 ESP-Fi fold checkpoint로 통합 확인:

```powershell
cd <저장소 경로>\csi-monitor
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-radar-monitor.ps1 `
  -Port COM7 `
  -ActivityModel ".\ml\v5_1\output\cross_validation\espfi\resnet18\fold-1\best.pt" `
  -ActivityHz 20 `
  -ActivityWindowFrames 950
```

checkpoint가 없으면 기존 monitor가 그대로 동작하고 행동 분류에는 `모델 대기`가 표시된다. CV fold checkpoint는 연결 시험용이다. 최종 서비스에는 자체 ESP32-S3 fine-tuning과 locked test를 통과한 모델만 사용한다.

---

## 11. 문제 해결

### PowerShell이 차단됨

`.ps1`을 더블클릭하지 말고 `powershell.exe -ExecutionPolicy Bypass -File ...` 형태로 실행한다. 학습 준비와 실행은 `.bat`이므로 이 문제와 무관하다.

### CUDA available이 False

1. `nvidia-smi` 확인
2. `.venv`에 CPU torch가 설치됐는지 확인
3. PyTorch 공식 설치 선택기에서 CUDA wheel 재설치

확인 명령:

```bat
..\..\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

### out of memory

- batch size 8 또는 4
- 다른 GPU 프로그램 종료
- `nvidia-smi`로 점유 프로세스 확인

### 데이터 파일 부족

- 2절의 폴더 이름과 깊이를 그대로 맞춘다.
- Git clone만으로 raw 데이터는 내려오지 않는다.
- UT-HAR `.csv`를 텍스트로 변환하지 않는다.

### 중간에 중단됨

`run-all-cv.bat`를 다시 실행한다. 완료된 fold는 재학습하지 않는다. 학습 도중 생성됐지만 `summary.json`이 없는 fold는 처음부터 다시 실행된다.

---

## 12. 학습 종료 후 할 일

1. `cv_summary.csv`의 모든 dataset/model 행이 folds 4인지 확인한다.
2. `RESULTS.md`를 열어 평균·표준편차를 확인한다.
3. 각 모델의 confusion matrix에서 낙상 누락과 오탐을 확인한다.
4. ESP-Fi 우승 CNN을 정한다.
5. 우승 모델의 ESP-Fi 환경 4-fold와 CSI-HAR 방 3-fold를 후속 실행한다.
6. 자체 ESP32-S3 데이터를 수집해 scratch와 공개 사전학습 fine-tuning을 비교한다.
7. 최종 checkpoint로 10/20/30Hz inference benchmark를 수행한다.

Git에 올릴 것:

- 코드
- 이 문서
- 개인정보 없는 `RESULTS.md` 집계

Git에 올리지 않을 것:

- `ml/dataset/raw/`
- `ml/v5_1/output/`
- `.venv/`
- 자체 raw CSI와 참가자·공간 metadata
- 승인되지 않은 공개 데이터 재배포본
