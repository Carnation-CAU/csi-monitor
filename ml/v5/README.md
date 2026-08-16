# v5: ESP-Fi CNN 단일-split 기준선

raw `950×52` amplitude를 받는 Simple CSI-CNN, CSI-ResNet18과 EfficientNet-B0 구현 및 단일 holdout 파이프라인이다. 세 공개 데이터셋의 정식 4-fold 36회 학습은 v5.1로 승계했다.

실습실에서는 [`../v5_1/LAB_TRAINING.md`](../v5_1/LAB_TRAINING.md)만 따른다. v5의 backbone과 공통 학습 함수는 v5.1에서 재사용한다.
