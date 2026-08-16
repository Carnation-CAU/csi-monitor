# 공개 CSI 행동 데이터셋

ESP-Fi HAR 외에 두 데이터셋을 내려받아 동일 모델 비교 준비를 마쳤다. 원본은 `raw/`에 있으며 Git에는 포함하지 않는다.

| 데이터셋 | 상태 | 입력 | 목표 라벨 | 용도 |
|---|---|---|---|---|
| UT-HAR | 설치 완료 | `250 x 90` amplitude | fall / walking / other_motion | 독립적인 3분류 비교 |
| CSI-HAR-3room | 설치 완료 | 연속 프레임, 114 subcarrier | walking / other_motion | 방 교차 일반화, 윈도우 검증 |
| OPERAnet | 보류 | 연속 Intel 5300 CSI | walking / other_motion | 약 34 GB라 필요할 때 추가 |

## 설치된 데이터

```text
raw/UT-HAR/UT_HAR/{data,label}/
raw/CSI-HAR-3room/room_{1,2,3}/
```

- UT-HAR: train 3,977 / validation 496 / test 500, 각 `250 x 90`.
- CSI-HAR-3room: 3개 방, 10개 연속 세션. ZIP 512,739,259 bytes, MD5 `711e794baee5a0bdab738cc85dcd2a2f` 검증 완료.

## 공통 라벨

`0=fall`, `1=walking`, `2=other_motion`으로 통일한다.

- UT-HAR의 `lie_down, pickup, run, sit_down, stand_up`은 `other_motion`.
- CSI-HAR의 `no_person`은 모션 분류에서 제외.
- CSI-HAR에는 낙상이 없으므로 이 데이터만으로 3분류 성능을 계산하지 않는다.

## 확인

```powershell
cd csi-monitor\ml\dataset
..\.venv\Scripts\python.exe .\inspect_public_datasets.py
..\.venv\Scripts\python.exe -m unittest .\test_public_datasets.py
```

`public_datasets.py`는 공통 로더, 크기 보간, 샘플별 정규화를 제공한다. 동일한 2D CNN에는 `[time, subcarrier]`로 넣는다.

## 공정한 비교 규칙

1. 모델 구조, optimizer, epoch, seed를 동일하게 고정한다.
2. 공식 train/validation/test 경계를 유지한다.
3. accuracy 외에 macro-F1, 클래스별 recall, confusion matrix를 기록한다.
4. UT-HAR와 ESP-Fi는 3분류로 비교한다.
5. CSI-HAR는 방 하나 전체를 test로 빼고 walking/other_motion 2분류로 평가한다.
6. 공개 데이터 성능과 우리 ESP32-S3 데이터 성능은 별도 표로 남긴다.

## 출처와 조건

- UT-HAR 처리본과 클래스: [SenseFi benchmark](https://github.com/xyanchen/wifi-csi-sensing-benchmark)
- CSI-HAR-3room: [Figshare 데이터셋](https://figshare.com/articles/dataset/14386892), CC BY 4.0
- CSI-HAR 설명: [Data in Brief 논문](https://doi.org/10.1016/j.dib.2021.107457)

SenseFi 코드의 MIT 라이선스가 UT-HAR 데이터 자체의 이용 조건을 대신하지 않는다. 외부 배포나 제품 학습 전에는 원 저자의 데이터 이용 조건을 별도로 확인한다.
