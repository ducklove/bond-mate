#!/usr/bin/env python3
"""bond-mate 데이터 생성기 — GitHub Actions(update-data.yml)가 호출하는 진입점.

    python generate_data.py                # 전체 수집
    python generate_data.py --skip-issuers # 금리·환율만 (EDGAR 는 직전 결과 유지)
    python generate_data.py --out data     # 출력 디렉터리 지정

EDGAR 수집은 발행사 13곳 × 공시 여러 건이라 수 분이 걸린다. 금리·환율은 30분
주기로 자주 돌리고 발행 이력은 하루 한 번만 갱신하려고 ``--skip-issuers`` 를 둔다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from bondmate import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bond-mate published JSON 생성")
    parser.add_argument("--out", default="data", help="출력 디렉터리 (기본 data)")
    parser.add_argument(
        "--skip-issuers",
        action="store_true",
        help="EDGAR 사채 발행 수집을 건너뛰고 직전 결과를 유지한다",
    )
    parser.add_argument("--quiet", action="store_true", help="경고 이상만 출력")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    snapshot = build.run(Path(args.out), skip_issuers=args.skip_issuers)

    rates, fx = len(snapshot["rates"]), len(snapshot["fx"])
    if not rates and not fx:
        print("금리·환율을 하나도 수집하지 못했습니다 — 실패로 처리합니다.", file=sys.stderr)
        return 1

    print(
        f"생성 완료 {snapshot['generated_at']} — "
        f"금리 {rates} · 환율 {fx} · 등급 {len(snapshot['credit'])} · "
        f"발행 {len(snapshot['offerings'])}건"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
