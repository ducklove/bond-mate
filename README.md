# bond-mate

전 세계 **금리·환율·국채·회사채**를 한곳에서 보는 정적 대시보드.
독립 실행되고, 필요한 화면만 다른 서비스에 임베드할 수 있다.

- 사이트: <https://ducklove.github.io/bond-mate/>
- 데이터: `data` 브랜치 (`data/*.json`) — GitHub Actions 가 갱신

## 무엇을 보여주나

| 화면 | 내용 |
|---|---|
| 개요 | 주요국 수익률 곡선, 국가별 10년물, 등급별 회사채 수익률 |
| 국채 | 국가별 만기 곡선 겹쳐보기(16개국), 만기별 표, 만기별 히스토리 |
| 기준금리 | 각국 정책금리·익일물·10년물과 장단기 차 |
| 환율 | 원화 크로스 8종 + 주요 통화쌍 8종, 통화별 히스토리 |
| 사채 | 미국 ICE BofA 등급별(AAA~CCC) 수익률·OAS, 한국 회사채 AA-/BBB- |
| 발행 | 구글·메타·오라클 등 대형 발행사의 채권 발행 이력과 **조달금리** |

모든 지표는 타일을 누르면 히스토리 그래프가 열리고 1/3/5/10년·전체로 구간을
좁힐 수 있다. 미국 10년물은 1962년부터, 달러/원은 1981년부터 들어 있다.

## 데이터 출처와 우선순위

같은 지표를 여러 곳이 주므로 **먼저 얹힌 값이 이긴다**. 순서:

1. **finance-pi** (`../finance-pi`, 라즈베리파이 `:8400`) — 이미 정규화된 원본.
   같은 값을 따로 긁으면 두 서비스 숫자가 갈리므로 살아 있으면 이걸 쓴다.
2. **한국은행 ECOS** — 국고채 전 만기(3M~50Y)·기준금리·회사채 AA-/BBB-.
3. **BIS CBPOL** — 주요국 중앙은행 정책금리. FRED 에는 미국·유로존밖에 없어
   이게 없으면 기준금리 화면이 미국과 유럽만 남는다. 한 요청으로 전 국가·1990년부터.
4. **일본 재무성** — JGB 전 만기 커브.
5. **FRED** — 미국 국채 커브, ICE BofA 등급별 회사채, 환율. API 키 없이 전체 히스토리.
6. **CNBC / 네이버** — 오늘자 시세만. 위 소스가 아직 못 따라온 최근 하루를 덮어쓴다.
7. **SEC EDGAR** — 회사채 발행 조건(FWP pricing term sheet).

> 정책금리 담당을 FRED 와 BIS 로 나눠 둔 이유: 같은 국가를 둘 다 다루면 어느 값이
> 나올지 순서에 좌우된다. 미국은 관행상 FF 목표 상단(3.75)이고 BIS 는 실효금리
> (3.62)라 정의부터 다르고, 영국은 FRED 의 `IUDSOIA` 가 Bank Rate 가 아니라
> SONIA 다. 그래서 미국·유로존은 FRED, 나머지는 BIS 로 못 박고 테스트로 고정했다.

> **finance-pi 현재 상태(2026-08-29 확인)**: 공개 엔드포인트가 관리자 토큰을
> 요구하고(401), LAN 에서 응답하지만 `macro.rates` 가 2026-07-17 에서 멈춰 있다
> (`ingest macro` 배치 미가동). 그래서 지금은 공개 소스가 실질 기본값이다.
> `FINANCE_PI_API_TOKEN` 을 주고 macro 적재가 재개되면 **코드 변경 없이**
> 1순위로 되돌아간다 — `finance_pi.probe()` 가 신선도까지 확인한 뒤 판단한다.

### 회사채 발행 조건은 어떻게 얻나

회사가 채권 가격을 확정하면 SEC 에 **pricing term sheet**(FWP, Rule 433)을
제출한다. 여기에 트랜치별 발행규모·표면금리·**만기수익률(=실제 조달금리)**·
**같은 만기 국채 대비 스프레드**·신용등급이 그대로 들어 있다.

term sheet 은 자유 서식이라 발행사마다 배치가 다르다. 네 가지를 모두 파싱한다:

| 형태 | 예 | 생김새 |
|---|---|---|
| 순차형 | Oracle | 트랜치 제목 아래 `라벨: 값` |
| 행렬형 | Alphabet | `Yield to Maturity:` 하나에 `2031 Notes: 4.991%` 가 줄줄이 |
| 선택자분리형 | Meta | `2031 Notes:` 와 값이 서로 다른 셀 |
| 한줄결합형 | Broadcom | `$750,000,000 ... 4.300% Senior Notes due 2031` 한 줄 |

XBRL 재무제표(`DebtInstrumentFaceAmount` 등)는 차원 정보가 소실돼 트랜치를
복원할 수 없어 쓰지 않는다.

## 로컬 실행

```bash
pip install -r requirements-dev.txt
python generate_data.py --skip-issuers   # 금리·환율만 (1분 남짓)
python -m http.server 8731 --directory . # templates/index.html 은 아래 참고
```

정적 사이트는 배포 시 조립된다(`templates/index.html` → `_site/index.html`).
로컬에서 그대로 보려면:

```bash
mkdir -p _site && cp templates/index.html _site/ && cp manifest.webmanifest _site/ \
  && cp -r static data _site/ && python -m http.server 8731 --directory _site
```

### 환경변수

| 변수 | 없으면 |
|---|---|
| `ECOS_API_KEY` | 국고채 전 만기·한국 회사채만 빠지고 나머지는 정상 |
| `FINANCE_PI_BASE_URL` | `http://cantabile.tplinkdns.com:8400` |
| `FINANCE_PI_API_TOKEN` | finance-pi 는 건너뛰고 공개 소스 사용 |
| `FINANCE_PI_ENABLED=0` | finance-pi 를 아예 시도하지 않음 |
| `FINANCE_PI_MAX_STALE_DAYS` | 기본 10일. 최신 관측이 이보다 오래되면 미사용 |
| `SEC_CONTACT_EMAIL` | 중립 기본값 사용. SEC 는 연락처 없는 UA 를 403 처리한다 |

> SEC WAF 는 User-Agent 에 `github` 이나 URL 이 들어가면 연락처가 유효해도
> 403 을 준다. 그래서 UA 는 이메일 하나만 괄호에 담는 최소 형식이다.

## 테스트

```bash
python -m pytest -q        # 62개 — 파서·조립·프론트 구조 계약
python -m ruff check .
```

## 임베드

필요한 화면만 iframe 으로 가져다 쓸 수 있다.

```
https://ducklove.github.io/bond-mate/?embed=<탭>&theme=<light|dark>
```

| 파라미터 | 설명 |
|---|---|
| `embed` | `overview` `government` `policy` `fx` `credit` `issuance` — 헤더·탭·푸터를 걷어내고 그 화면만 |
| `theme` | `light` / `dark`. 생략하면 보는 사람의 시스템 설정 |
| `bg` | `transparent` 를 주면 배경을 비워 부모 카드에 녹인다(기본은 테마 배경을 칠함) |
| `tab` | 독립 실행에서 초기 탭 지정 (딥링크) |
| `data` | 스냅샷·히스토리 위치 재지정 |

임베드된 페이지는 내용 높이가 바뀔 때 부모에 알린다:

```js
window.addEventListener('message', (event) => {
  if (event.data?.source === 'bond-mate' && event.data.type === 'height') {
    iframe.style.height = event.data.height + 'px';
  }
});
```

탭 키와 파라미터 이름은 부모가 URL 에 박아 쓰는 **계약**이라 바꾸지 않는다
(`tests/test_frontend_structure.py` 가 고정).

## 발행 JSON

| 파일 | 내용 |
|---|---|
| `data/current.json` | 최신 스냅샷 — 소비자(value-invest 등)가 읽는 계약 파일 |
| `data/rates.json` | 국채·정책금리 히스토리 |
| `data/fx.json` | 환율 히스토리 |
| `data/credit.json` | 등급별 회사채 수익률·OAS 히스토리 |
| `data/issuers.json` | 회사채 발행 이력 전체 |

히스토리는 병렬 배열(`{"d": [...], "v": [...]}`)이고, 구간별로 해상도를 낮춘다
— 최근 3년 일간, 3~10년 주간, 그 이전 월간. 미국 10년물 6만여 관측이
1,700여 포인트로 떨어져 Pages 로 서빙할 만한 크기가 된다.

**소스를 바꿨다면 히스토리를 다시 쌓아야 한다.** 히스토리는 upsert 라 옛 소스의
관측치가 그대로 남고, 새 소스보다 날짜가 뒤면 그게 최신값 자리를 차지한다:

```bash
python generate_data.py --reset-series GB_BASE
```

운영에서는 `update-data` 워크플로를 `reset_series` 입력과 함께 수동 실행한다.

## 갱신 주기

| 무엇 | 언제 |
|---|---|
| 금리·환율·등급별 회사채 | 30분마다 (`update-data.yml`) |
| 회사채 발행 이력 | 하루 한 번, UTC 02:10 (KST 11:10) |
| 사이트 배포 | `master` push, 또는 데이터가 바뀌면 자동 트리거 |

## 구조

```
bondmate/
  catalog.py      국가·만기·등급·환율쌍·발행사 SSOT
  build.py        수집 → 병합 → published JSON 조립
  history.py      히스토리 저장 포맷·해상도 축소
  http.py         공유 세션·재시도·User-Agent
  sources/        finance_pi · fred · ecos · mof · cnbc · naver · edgar
templates/        index.html (배포 시 _site 로 조립)
static/           CSS 1개 + JS 9개 (빌드 없음, script 순서가 의존성 계약)
generate_data.py  Actions 진입점
```
