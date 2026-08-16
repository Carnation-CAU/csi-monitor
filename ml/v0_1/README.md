# v0.1 오류 분석

ESP-Fi HAR의 수집 환경과 현재 보유 데이터 범위를 확인하고, v0의 낙상 오분류를
원래 행동 및 참가자별로 분석한다.

비교하는 전략은 다음과 같다.

1. 3개 목표 레이블을 직접 학습
2. 7개 원래 행동을 학습한 뒤 `walking / fall_suspected / other_motion`으로 병합
3. 위 두 방식에 단순 피크 정렬 및 전후 에너지 특징을 추가

모든 비교는 기존과 동일하게 참가자 한 명 전체를 시험 데이터로 남기는
leave-one-participant-out 방식이다.

```powershell
python ml\v0_1\analyze_errors.py
```

의존성은 `ml/v0/requirements.txt`와 같다. 생성되는 상세 CSV와 JSON은 Git에
포함하지 않는 `ml/v0_1/output/`에 저장된다.

해석과 다음 학습안은 [RESULTS.md](RESULTS.md)에 정리했다.
