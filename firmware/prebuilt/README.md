# 미리 빌드된 펌웨어

ESP-IDF 설치 없이 보드에 바로 업로드할 수 있는 완성 바이너리다.
사용 절차는 [Windows 세팅 5-A](../../docs/setup-windows.md#5-a-미리-빌드된-바이너리로-업로드-권장) 또는
[macOS 세팅 5-A](../../docs/setup-macos.md#5-a-미리-빌드된-바이너리로-업로드-권장)를 참고한다.

## 출처

| 항목 | 값 |
|---|---|
| ESP-IDF | `v5.0.2` |
| ESP-CSI 커밋 | `740083e5ac0067b8e5ba812d2d08fd94f8ce0348` |
| 적용 패치 | `firmware/patches/esp-csi-project.patch` |
| 대상 | `esp32s3` |
| 빌드일 | 2026-08-04 |

이 바이너리에는 프로젝트 패치가 적용되어 있다. 즉 `rf_channel` 채널 전환 명령과
ESP-NOW 채널 제어 패킷이 포함되며, 기본 채널은 상위 저장소의 `11`이 아니라 `6`이다.

## 파일과 플래시 오프셋

TX 송신기 — flash size `2MB`

| 오프셋 | 파일 |
|---|---|
| `0x0` | `tx/bootloader.bin` |
| `0x8000` | `tx/partition-table.bin` |
| `0x10000` | `tx/csi_send.bin` |

RX 수신기 — flash size `4MB`

| 오프셋 | 파일 |
|---|---|
| `0x0` | `rx/bootloader.bin` |
| `0x8000` | `rx/partition-table.bin` |
| `0x1d000` | `rx/ota_data_initial.bin` |
| `0x20000` | `rx/console_test.bin` |

**RX 앱은 `0x20000`이다.** TX와 같은 `0x10000`에 구우면 부팅되지 않는다.

## SHA-256

```text
2325e17fcb44c4dfd7bc0a81cc9b8e8412cab4c4377970de1f385ac53a4e308e  tx/bootloader.bin
7f00b6c042a89b15b0cac534f82ed988caf29278ff5700b0c511eb1b5bb7c820  tx/partition-table.bin
9039f1f1f27148fbbd52625e23c59aa771404aa0f7b60a9295e3bc1a2c18a6da  tx/csi_send.bin
ba23caced92896a00ad10aab3c6735314edc08833f8531fe318339b5c40d45e2  rx/bootloader.bin
3a6d202e79d73c3d2131121c780fdd0f63f484e265cc840eb4eb556a90a2a4b3  rx/partition-table.bin
7d2c7ac4888bfd75cd5f56e8d61f69595121183afc81556c876732fd3782c62f  rx/ota_data_initial.bin
174ad1e24fb1a275ce7f877c7f20d00437a7690574af3764d52bf3d83a5c9b1c  rx/console_test.bin
```

내려받은 파일이 손상되지 않았는지 확인할 때 사용한다.

```bash
sha256sum -c <<'EOF'
9039f1f1f27148fbbd52625e23c59aa771404aa0f7b60a9295e3bc1a2c18a6da  tx/csi_send.bin
174ad1e24fb1a275ce7f877c7f20d00437a7690574af3764d52bf3d83a5c9b1c  rx/console_test.bin
EOF
```

이 해시는 **전송 무결성 확인용**이다. 직접 다시 빌드한 바이너리와 대조하는 용도가 아니다.
`CONFIG_APP_REPRODUCIBLE_BUILD`가 비활성이라 같은 커밋·같은 패치로 빌드해도 해시는 달라진다.

## 갱신 시점

펌웨어 C 코드나 `esp-csi` 고정 커밋을 바꾸면 이 폴더도 함께 갱신하고, 위의 출처와
SHA-256을 새 값으로 교체한다.
