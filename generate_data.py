#!/usr/bin/env python3
"""bond-mate 데이터 생성기 — GitHub Actions(update-data.yml)가 호출하는 진입점.

    python generate_data.py                # 전체 수집
    python generate_data.py --skip-issuers # 금리·환율만 (EDGAR 는 직전 결과 유지)
    python generate_data.py --out data     # 출력 디렉터리 지정

EDGAR 수집은 발행사 13곳 × 공시 여러 건이라 수 분이 걸린다. 금리·환율은 30분
주기로 자주 돌리고 발행 이력은 하루 한 번만 갱신하려고 ``--skip-issuers`` 를 둔다.

GitHub Actions 에서는 ``$GITHUB_OUTPUT`` 에 ``publish=true|false`` 를 남긴다. 값이
그대로인 실행은(하트비트 간격 안이면) 커밋·배포를 건너뛴다 — :func:`build.publish_due`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from bondmate import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bond-mate published JSON 생성")
    parser.add_argument("--out", default="data", help="출력 디렉터리 (기본 data)")
    parser.add_argument("--fx-only", action="store_true", help="최신 환율만 갱신하고 다른 데이터는 유지")
    parser.add_argument(
        "--skip-issuers",
        action="store_true",
        help="EDGAR 사채 발행 수집을 건너뛰고 직전 결과를 유지한다",
    )
    parser.add_argument(
        "--reset-series",
        default="",
        help=(
            "쉼표로 구분한 시리즈 ID. 직전 히스토리를 버리고 새 소스로만 다시 쌓는다 "
            "— 한 시리즈의 소스를 바꿨을 때 옛 소스의 관측치가 남아 최신값을 가리는 걸 푼다."
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="경고 이상만 출력")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    reset_series = {s.strip() for s in args.reset_series.split(",") if s.strip()}
    previous = build.read_json(Path(args.out) / build.SNAPSHOT_FILE)
    if args.fx_only:
        snapshot = build.refresh_fx(Path(args.out))
    else:
        snapshot = build.run(Path(args.out), skip_issuers=args.skip_issuers, reset_series=reset_series)

    rates, fx = len(snapshot["rates"]), len(snapshot["fx"])
    if not rates and not fx:
        print("금리·환율을 하나도 수집하지 못했습니다 — 실패로 처리합니다.", file=sys.stderr)
        return 1

    publish = build.publish_due(previous, snapshot)
    _write_output("publish", "true" if publish else "false")

    print(
        f"{'생성 완료' if publish else '변경 없음(발행 생략)'} {snapshot['generated_at']} — "
        f"금리 {rates} · 환율 {fx} · 등급 {len(snapshot['credit'])} · "
        f"발행 {len(snapshot['offerings'])}건"
    )
    return 0


def _write_output(name: str, value: str) -> None:
    """GitHub Actions 단계 출력. 로컬 실행에서는 아무것도 하지 않는다."""
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


if __name__ == "__main__":
    raise SystemExit(main())
