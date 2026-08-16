# CSI 행동 분류 ML

목표는 재실이 확인된 구간에서 `fall`, `walking`, `other_motion`을 분류하는 것이다. 재실 판단은 이 모듈의 책임이 아니다.

현재 진행 상태:

- v0~v0.1: ESP-Fi 데이터 타당성과 오류 분석
- v1~v1.1: 통계 특징 기반 계층 분류와 행동 범위 실험
- v2: DTW 특징 실험
- v3: gateway가 자른 실제 이벤트 구간 검증
- v4: 고전 ML 모델 비교
- v5: raw CSI 기반 Simple CNN·ResNet18 GPU 학습

공개 데이터 현황과 공통 라벨은 [`dataset/README.md`](dataset/README.md), 전체 개발 전략은 [`strategy.md`](strategy.md), 실습실 PC 학습 방법은 [`v5/README.md`](v5/README.md)를 참고한다.
