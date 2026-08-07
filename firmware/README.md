# 펌웨어

초기 기준선은 `third_party/esp-csi`의 공식 예제를 기반으로 사용한다.

- TX: `examples/get-started/csi_send`
- RX: `examples/esp-radar/console_test`

공식 예제 재현과 기준선 수집이 끝나기 전에는 이 폴더에 자체 펌웨어를 만들지 않는다.

현재 사용자 승인에 따라 공식 예제 내부에 채널 동기 전환 기능만 추가했다.
CSI 수집과 Radar 움직임 판정 알고리즘은 Espressif 공식 구현을 유지한다.
