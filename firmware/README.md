# 펌웨어

초기 기준선은 `third_party/esp-csi`의 공식 예제를 기반으로 사용한다.

- TX: `examples/get-started/csi_send`
- RX: `examples/esp-radar/console_test`

공식 예제 재현과 기준선 수집이 끝나기 전에는 이 폴더에 자체 펌웨어를 만들지 않는다.

현재 사용자 승인에 따라 공식 예제 내부에 HT20 고정, 기본 채널 6,
채널 1·6·11 동기 전환과 실제 RF 설정 로그를 추가했다.
CSI 수집과 Radar 움직임 판정 알고리즘은 Espressif 공식 구현을 유지한다.

일상적인 플래시는 소스 없이 `firmware/prebuilt`와 운영체제별
`scripts/flash-prebuilt.*`만 사용한다. `third_party/esp-csi`는 C 소스를 다시
빌드할 때 `scripts/fetch-esp-csi.*`로 재생성하는 로컬 작업 폴더다.
