# Third-party sources

`scripts/fetch-esp-csi.ps1`로 Espressif `esp-csi`를 내려받는다.

현재 기준 commit:

```text
740083e5ac0067b8e5ba812d2d08fd94f8ce0348
```

이 값은 `versions.json`에도 기록되어 있다. 이 커밋은 최신 코드가 ESP-IDF 5.0.2에 없는 ESP-NOW API를 도입하기 직전의 공식 커밋이다. 다른 PC에서는 clone 후 이 commit을 checkout하여 같은 기준을 사용한다.
