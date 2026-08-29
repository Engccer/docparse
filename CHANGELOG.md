# 변경 이력

이 프로젝트의 주요 변경 사항을 버전별로 정리합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/)를 따릅니다.

## 2026-08-30 (규칙마다 근거 강도 병기 + 비PDF 표 내부 모순 정정)

- **`references/tier-rules.md`의 모든 판정 절에 `*근거:*` 줄 추가**(25개 절). 규칙이 문서 몇 건에서 나왔는지(`n=12`·`n=1`·`미표기`·`능력표`)를 규칙 옆에 적는다. 종전에는 12건에서 나온 규칙과 1건에서 나온 규칙이 같은 문장 형식이라, 결과가 어긋났을 때 규칙과 문서 중 무엇을 먼저 의심할지 알 수 없었다. 파일 첫머리에 읽는 법 표를 두고, 하위 절은 상위 절 근거를 승계한다.
- 분포 실측(표기 25개 = 판정 규칙 21 + 비판정 4): **`n=1` 9**, `n=2` 2, `n=3` 2(`n≈3` 포함), `n=12` 1(프랑스어), `미표기` 3, 상위 절 승계 2, 산출물 2종 대조 1, 단계별 1(HWP/HWPX: 1~2단계 n=33 / 4~5단계 n=1) / 능력표 2·정책 1·방법 규칙 1. **판정 규칙 21개 중 9개가 단일 문서**에서 나왔다. 규칙이 틀렸다는 뜻이 아니라 일반화 범위가 그 문서 하나라는 뜻이며, `parser-eval` Mode A의 우선순위가 여기서 나온다.
- **근거 세는 단위를 규칙으로 못 박았다**: 매수·학급·표본은 문서 수가 아니다(답안 80매도 문서로는 2건), 같은 문서를 여러 번 평가한 것도 문서 수를 늘리지 않는다, 장부가 두 산출물을 한 `doc.id`로 기록하면 그것이 기준이다. 첫 표기에서 손글씨 절을 `n≥5`(최강 등급)로, 합본 절을 `n=1`로 매긴 것이 정확히 이 단위 혼동이었다. 즉 **판정 규칙 21개 중 10개(약 절반)가 단일 문서에서 나왔다.** 규칙이 틀렸다는 뜻이 아니라 일반화 범위가 그 문서 하나라는 뜻이며, `parser-eval` Mode A의 우선순위가 여기서 나온다.
- **비PDF 포맷 표의 내부 모순 정정**: 같은 파일의 「XLSX·DOCX 로컬 결정론 파서」 절과 SKILL.md 티어 표는 DOCX·XLSX에 로컬 파서를 1순위로 두는데, 아래 「비PDF 문서 포맷별 파서 선택」 표만 여전히 `Upstage + LlamaParse v2`였다(2026-08-11 로컬 티어 신설 때 함께 갱신되지 않은 잔재). 두 표를 로컬 파서 우선으로 맞추고, 호환성 매트릭스의 `hwpx_local` 열을 `로컬 결정론 파서` 열로 넓혀 pdfplumber·docx_local·xlsx_local을 함께 담았다.
- 매트릭스에 `O`의 뜻을 명시: **입력으로 받을 수 있다는 뜻이지 잘한다는 뜻이 아니다.** 형식 불가와 성적 미달을 한 표에 섞으면 초기 선점 파서 외에는 재평가 기회가 오지 않는다(`parser-eval/references/capability.md`).
- **스캔 티어 절의 대역 오기재 정정**: 「텍스트 레이어 없음」 절이 80p 스캔 의무기록 A등급 실측을 **medium(16~60p) 항목에** 인용해 왔는데, 같은 절의 정의상 **80p는 large(61~100p)**다. 실측이 있는 쪽은 large이고 medium은 파생 배정인데 정확히 반대로 적혀 있었다(근거 마커를 달면서 이 오류를 검증 없이 승계할 뻔한 것을 별도 컨텍스트 리뷰가 잡았다). 인용을 large 항목으로 옮기고 medium은 "이 대역 자체의 실측은 없다"로 명시.
- 읽는 법 표에 없던 `n≈N`(건수가 기록으로 확정되지 않음)을 정의하고, 정의 없이 쓰던 `n=N subset` 표기는 **폐기**했다(상위 절 승계로 적는다 — 부분집합에 새 번호를 매기면 독립 근거로 오독된다).
- **`n=33` 과대 표기 정정**: HWP/HWPX 절차 절은 7단계인데 33종 근거는 **1~2단계(hwpx-tomd 변환 정확도)에만** 해당한다. 4~5단계(`hwpx_enrich` 보강·kordoc 대조)는 2026-08-28 단일 554쪽 보고서(n=1)이고 6단계는 변환 실패 대응이라 문서 수 개념이 없다. 절 전체가 파일에서 가장 두꺼운 근거를 두른 꼴이었다. 단계별로 쪼개 적고, 「여러 단계를 담은 절은 가장 두꺼운 근거를 절 전체에 적지 않는다」를 읽는 법에 규칙으로 넣었다.

## 2026-08-29 (수식 판정 방법 정정: 소실이 아니라 PUA 잔존)

- `references/tier-rules.md` 수식 시험지 절의 **기전 서술이 틀렸던 것을 정정**. "ODL·Upstage가 수식 글리프를 통째로 버린다 / 텍스트 레이어 추출이 빈 문자열을 반환한다"는 사실이 아니다. 실제로는 **HancomEQN 글자가 유니코드 사용자 정의 영역(PUA, U+E000~F8FF) 코드로 그대로 잔존**하고 렌더만 되지 않는다. 사람이 못 읽는 결과는 같지만 **탐지 방법이 달라진다**.
- 그래서 **"조사만 남고 피수식어가 빈 칸"이라는 판정 방법을 폐기**하고 **PUA 코드포인트 계수**로 교체. 자리는 비어 있지 않고 PUA 바이트가 차지하고 있다(같은 문서 조사 앞 공백 폭 실측 {0칸 11, 1칸 454, 2칸 이상 0}).
- 실측 재확인(서울대 78쪽 기출): PUA 덩어리 LlamaParse 0 / Upstage 731 / ODL 646(코드포인트 0 / 1,227 / 1,275), LaTeX 토큰 450 / 0 / 0.
- **판정은 절대 개수가 아니라 밀도로 한다.** 수식 없는 한컴 PDF에서도 ODL이 원문자·기호를 PUA로 흘려 14·102·225 덩어리가 나온다(대조 파서 출력 38종 전수 확인). 본문 1만 자당 PUA로 재면 수식 없는 문서 6.3~8.2 대 수식 시험지 114.1~211.6으로 14~34배 벌어진다. 임계는 1만 자당 100.
- 해설 표 라벨 회수 수치도 실측으로 교체: `활용 모집단위` Upstage·ODL 15/15, LlamaParse 9/15(절 제목이 첫 열 라벨 셀에 병합). 이미지 축 한 줄 추가(Upstage figure-description의 사실 오류, ODL 이미지 참조 0).

## 2026-08-29 (평가 도구 parser-eval 이관)

- **`scripts/score_transcription.py`·`scripts/diff_fidelity.py`를 `parser-eval` 스킬로 이관.** 두 스크립트는 파싱 도구가 아니라 **파서를 견주는 도구**다. 파서 비교평가가 다섯 건 쌓이는 동안 그중 두 건이 HWPX 엔진 비교(hwpx-tomd vs python-hwpx)였는데, 그건 docparse가 아니라 `hwpx-automation`·`hwpx-tomd` 영역이라 평가 절차를 docparse 안에 두면 소속이 어긋난다. 평가 워크플로우는 docparse·hwpx-automation·check-stack-updates 세 스킬을 가로지르므로 독립 스킬(`parser-eval`)로 분리했다.
- `SKILL.md` 스크립트 표에서 두 항목 제거 + 이관 안내 한 줄. `references/tier-rules.md`의 `diff_fidelity.py` 호출 경로, `references/handwriting-cascade.md`의 CER/WER 채점 도구 위치를 새 경로로 갱신.
- 파싱 방법·프롬프트(캐스케이드 절차, 티어 규칙)는 그대로 docparse가 정본이다. 옮긴 것은 **견주고 채점하는 절차**뿐이다.

## 2026-08-29 (수식 시험지·pdftotext 함정)

- `references/tier-rules.md`: **수식이 있는 시험지는 LlamaParse v2가 유일한 Primary**. ODL·Upstage는 HancomEQN 계열 수식 글꼴의 변수·수치를 통째로 버린다(서울대 78쪽 면접·구술고사 기출 실측). 판정 방법과 역할 분담(수식은 v2, 해설 표 행 구조는 Upstage 기준으로 대조) 명시.
- `references/tier-rules.md`: **`has_text_layer: true` 인데 pdftotext만 한글을 못 뽑는 경우**. 한컴 PDF에서 poppler가 한글을 공백으로 떨구지만 ODL·LlamaParse·Upstage는 정상 추출한다. pdftotext 결과가 비었다고 스캔 티어로 승격하지 말 것.

## 2026-08-28 (하이브리드 경로)

- `hwpx_enrich.py`: `--title-table`(제목 역할 2칸 표 승격), `--heading-regex` 상대 수준 `+N`(같은 규칙 형제 동수준·H1 비부모), 정규식이 스타일 승격보다 우선·목차 잔재(끝이 ' 숫자') 제외, 레이아웃 표 판정 `<br>` 분할, 구역 머리말 재출력 중복 H1 제거, 바닥글 앞·뒤 자리 쪽 번호 인식.
- SKILL.md: 초안 HWP + 인쇄 PDF 하이브리드 절차(구조는 HWP·내용은 PDF, 간지 표 H1, 그림→텍스트 재조판 함정, PUA 글리프) 추가.

## [3.22] - 2026-08-28

### 추가
- **`scripts/hwpx_enrich.py`**: hwpx-tomd 출력에 HWPX 메타를 결정론적으로 입히는 보강기. 개요 스타일→`#` 제목, `charPr` 취소선→`~~`·글자색→`<mark>`, 인쇄 PDF 쪽 번호→`<!-- p.N (pdf M) -->`(pdftotext 쪽 텍스트와 전역 LIS 정렬, 앞으로만 넓히는 탐색은 반복 조사지에서 튀어 폐기), 간지 레이아웃 표·머리말 잔재 삭제. 문단 단위 정확 일치로만 치환하고 미매칭은 보고서에 남긴다. 실측: 554쪽 교육부 정책연구 최종보고서 HWP에서 제목 301·서식 런 729·쪽 주석 134, 원본 오탈자 임의 교정 0건.
- **`scripts/apply_corrections.py`**: 정본 수정 목록 CSV 적용기(오탈자·개인정보·표기 정규화·원본 결함 기록). 원문 0회면 오류 종료, 치환 후 잔존 검사, 원본 쪽 자동 채움.
- SKILL.md **Step 0.5 편집 원본 탐색** 신설: PDF 파싱 전에 HWP·HWPX·DOCX 편집 원본을 먼저 찾는다(원본이 옆 폴더에 있었는데 PDF를 LLM으로 파싱한 사고의 교훈).
- tier-rules **「인쇄용 책자 PDF의 여러 쪽에 걸친 표·병합셀」** 절 신설(연속 표 잇기·병합값 반복 기입·1:1 대응 금지·셀 위치 대조 필수). fusion-prompt의 「병합셀 평탄화, 손실 허용」을 「병합값 반복 기입, 1:1 대응 생성 금지」로 교체. postprocess에 `<page_header>`·`<u>`·`< 표`·가운뎃점 공백 패턴 추가. Step 7에 원본 오탈자 임의 교정 금지 명시.
- HWP 티어 갱신: kordoc은 rowSpan/colSpan 명세·장 제목 보조 메타로 재평가(쪽 번호는 추정이라 불채택), pyhwp·한컴 COM의 strikeout은 오판 확인(표지 제목까지 취소선)으로 불채택, hwp2hwpx 예외 유형별 폴백 기록.

### 엔진(hwpx-tomd 0.2.2, 이 작업에서 발견·수정)
- 다중 run 문단의 run 경계 공백 삽입(「내용 은 파란색 으로」), 셀 안 중첩표 평탄화 시 단어 접합(「학습지도생활지도와」), 표·그림 `<hp:caption>` 272건 누락(단어 recall이 목차 중복 문구 때문에 못 잡던 손실). 세 건 모두 합성 HWPX 회귀 테스트와 함께 엔진 저장소에 반영.

## [3.21] - 2026-08-11

### 추가
- **Office 로컬 결정론 파서 2종 신설**: `parsers/xlsx_local_parse.py`(openpyxl)·`parsers/docx_local_parse.py`(python-docx). XLSX·DOCX는 셀 값·병합 범위·헤딩 스타일이 XML에 명시된 포맷이라 Tier 0 철학(원본이 명시적이면 LLM 추론은 하방 위험)을 그대로 확장한다. `assess_document.py`가 두 포맷에서 로컬 파서를 추천 선두에 배치(구: Upstage·LlamaParse만).
  - xlsx_local: 병합은 범위 명시 기록(거부 아님), 숨김 행·열 데이터 보존·고지, 미계산 수식은 원문 보존. 검증 게이트는 openpyxl 추출값 전체 vs 원시 XML 자체 해석(zipfile+ElementTree 독립 파스)의 시트 단위 값 멀티셋 대조 — 불일치 시 출력 미작성.
  - docx_local: 본문 블록(헤딩·단락·표) 문서 순서 보존, document.xml 전수 recall 토큰 대조("가장 가까운 조상 w:p" 집계로 run 분절 안전). 텍스트박스·필드 텍스트는 누락으로 반드시 드러나 거부, 각주·미주 텍스트·중첩 표도 거부(조용한 유실 차단).
  - 실측(2026-08-11): 실제 법률안 DOCX 토큰 1,063건 완전 일치 PASS, 병합 263범위 동아리 명부 XLSX PASS(수식 캐시·숨김 열 고지 포함), 각주 있는 3,611토큰 보고서 정직 거부, 서드파티 텍스트박스 픽스처 누락 토큰 명시 거부. 합성 파일 테스트 21종 GREEN.
  - 구현 함정 기록: python-docx 병합 감지에서 lxml 프록시 `id()`만 저장하면 GC 후 id 재사용으로 정상 셀을 병합 오인(실측 재현) — 참조 보관으로 해결(tier-rules 기록).
- **`pdfplumber_parse.py --strategy text` (opt-in)**: 괘선 없는 정렬 표를 pdfplumber·PyMuPDF 양쪽 text 전략 교차 투표 + 단어↔셀 대조로 지원. 산문 오인은 추정 열 경계가 단어를 관통해 쪼개므로 단어↔셀 대조가 거부함을 실측(두 엔진이 같은 43x14 쓰레기 표에 수렴했으나 거부). 렌더링 시 데이터 없는 빈 간격 행 제거(lines 전략의 빈 행은 양식 정보라 보존). PASS 의미의 경계(열 구획 정보 부재)와 text 전략 교차 투표의 독립성 한계를 tier-rules에 명시.
- `requirements.txt`·`scripts/check_env.py`에 openpyxl·python-docx(>=1.1.0 핀) 추가(무료·로컬 군). SKILL.md 티어 표·파서 표·비교표·README·tier-rules에 xlsx·docx 티어와 `xlsxlocal`·`docxlocal` fused 토큰 반영.
- 별도 컨텍스트 코드 리뷰 보강(BLOCKING 2건 포함 9건): ①머리글·바닥글이 document.xml recall 사각지대에서 무경고 유실된 채 PASS로 위장하던 구멍을 파트별 추출(표·첫/짝수 페이지 변형 포함)+파트별 recall 검증으로 봉합 ②raw 집계가 w:tab·w:br를 구분자 없이 이어붙여 소프트 줄바꿈·탭이 있는 흔한 문서를 전부 오거부하던 결함을 공백 합류로 해소 ③그룹 숨김 열(min~max) 고지 전개 ④차트시트 등 openpyxl 로드 실패의 우아한 거부 ⑤`t="d"`(ISO 날짜 셀) 크래시 방지 ⑥미계산 수식 원문은 값 검증 대상이 아님을 한계로 명시 ⑦text 전략 표 미검출 메시지 분리 ⑧python-docx 하한 핀 ⑨죽은 코드 제거. 재검증(9건 전부 CONFIRMED) 후속 4건 추가 반영: w:noBreakHyphen(하이픈)·w:ptab(공백)·단락 중간 페이지/단 나눔(w:br type=page/column은 빈 문자열) 대칭 번역으로 오거부 3종 해소, w:sym(심볼 글리프)은 양쪽 관점이 모두 못 읽어 recall로도 안 잡히는 대칭 침묵 유실이라 존재 감지 시 거부로 전환. 최종 회귀 테스트 46종 전체 GREEN, 실문서 재실측 결과 불변.

## [3.20] - 2026-08-10

### 추가
- **`pdfplumber_parse.py` 독립 2엔진 교차 투표**: 기존 자가검증(격자↔좌표)은 pdfplumber 내부의 두 관점이라 열 경계 오인처럼 같은 상류 결함을 공유하는 오류를 통과시킨다(교란 주입 테스트로 한계 재현). 구현을 공유하지 않는 PyMuPDF `find_tables()`로 같은 표를 다시 추출해 표 개수·구조(행x열)·셀 내용을 셀 단위 대조하는 `crosscheck_with_fitz` 추가 — 두 독립 엔진이 같은 결과에 도달해야만 PASS. 교차 엔진 불일치도 경고로 집계되며, 경고 시 출력 미작성·기존 티어 승격 동작은 동일. PyMuPDF 미가용 환경에서는 교차 투표만 생략하고 그 사실을 출력에 명시한다(추가 의존성 없음: 이미 `assess_document.py` 의존성). 실측: 합성 결함 4종(공유 상류 결함·값 교체·표 누락 포함) 전부 검출, 달력형 학사일정 2p에서 세로 병합 월 라벨의 엔진 간 배치 차이 2건 검출(병합 거부의 독립 근거), 175p 행정 길라잡이(산문 혼합)에서 교차 불일치 142건으로 거부 보강(34.5초·비용 0), 교차 투표 오버헤드 2p 기준 약 0.6초(2026-08-10).
- 별도 컨텍스트 코드 리뷰 보강: 엔진 간 페이지 수가 다르면 zip 절단으로 초과 페이지의 표가 검증을 탈출하던 구멍 차단(BLOCKING), CropBox != MediaBox 문서에서 두 엔진 좌표계 차이(fitz=cropbox 원점, pdfplumber=mediabox 원점)로 인한 오거부를 mediabox 기준 평행이동으로 해소, fitz 런타임 오류는 불일치로 간주(fail-closed), 임포터(가짜) fitz 모듈 가드, 교차 투표 생략 시 경고 요약이 "불일치 0건"으로 오독되지 않게 표기 분리. 회귀 테스트 12종(공유 상류 결함·페이지 수·CropBox 포함) 전체 GREEN.

## [3.19] - 2026-08-10

### 추가
- **Tier 0 (결정론 우선 게이트) 신설**: 벡터 괘선으로 그려진 정형 표 + 텍스트 레이어 PDF(시간표·명렬표·집계표 등 행정 문서)는 페이지 수 티어보다 먼저 `parsers/pdfplumber_parse.py`(신규, 로컬·무료·비-LLM)를 시도한다. 격자 모델(`extract_tables`)과 좌표 모델(`extract_words`)을 셀 단위 양방향 대조하는 자가검증 내장 — 열 배정 오류·값 소실을 기계로 검출한다(교란 주입 테스트로 확인). 경고(셀 불일치·미배정 단어·병합 의심 셀·표 미검출) 시 **출력 파일을 만들지 않고** 기존 티어로 승격하므로 기존 동작을 해치지 않는다. 빈 셀은 빈 문자열로 보존, 표 밖 텍스트(제목·캡션)는 원문 위치 순서대로 보존, 병합(colspan/rowspan) 셀은 None 셀로 감지 즉시 경고. 실측 동기: 46p 시간표 PDF에서 클라우드 파서 2종이 권고됐으나 pdfplumber가 셀 647개를 약 1초·비용 0으로 누락·중복 없이 추출(2026-08-10).
- `requirements.txt`·`scripts/check_env.py`에 pdfplumber 추가(무료·로컬 군). SKILL.md 티어 표·파서 비교표·README·tier-rules.md에 t0 티어 반영.

### 수정
- **`assess_document.py`의 `table_hint` 휴리스틱 교체**: 파이프/탭 문자 카운트 → `page.get_drawings()` 벡터 선분(사각형 4변 포함) 교차 판정(수평·수직 각 3개 이상 상호 교차 = 격자). 구 휴리스틱은 괘선이 벡터 그래픽이지 문자가 아니라서 선으로 그린 표를 원천적으로 못 잡았다. 같은 위치의 선분 구간은 겹치거나 1pt 이내로 맞닿을 때만 병합하고(간격 보존) 교차 허용 오차를 1pt로 좁혀, 밑줄·단일 테두리 상자·2pt 간격 이중 테두리·정렬된 분리 카드 상자를 격자로 오판하지 않는다(별도 컨텍스트 코드 리뷰가 이중 테두리·카드 레이아웃 오탐을 실측으로 잡아 보강, 합성 PDF 양성 3종·음성 4종으로 재검증). 점선(대시) 괘선 표는 미검출로 기존 티어에 남는다(안전 방향 미탐, tier-rules 적용 경계 참조).
- **`recommend_parsers()`의 죽은 파라미터 `table_hint` 해소**: 계산만 되고 본문에서 참조되지 않던 값을 실제 사용 — `pdf` + `has_text_layer` + `table_hint`면 `pdfplumber`를 추천 선두에 배치.

## [3.18] - 2026-07-05

### 변경
- **최종 fused 파일명에 파서 조합 명시**: `_fused_v3.md` → `_fused_v3_<파서조합>.md`. 파일명만으로 어느 파서를 통합했는지 알 수 있도록, **실제로 내용이 반영된 파서**를 Primary부터 `+`로 나열(예: LlamaParse Primary+Upstage 패치 → `_fused_v3_llamaparse+upstage.md`, 단독 채택 → `_fused_v3_mistral.md`·`_fused_v3_hwpxlocal.md`). 단순 대조만 하고 병합하지 않은 파서는 제외. 파서 토큰은 개별 출력 접미사와 동일(`llamaparse`·`upstage`·`gemini`·`mistral`·`opendataloader`·`hwpxlocal`·`corepin`·`gvision`).
- SKILL.md: Step 4에 명명 규칙 신설, Step 6b에 보조 파서 반영 시 `+<파서>` rename 지침, Step 8에 저장 직전 파일명·반영 파서 일치 검증 추가.
- `.gitignore`: `*_fused_v3.md` → `*_fused_v3*.md`로 확장(파서 접미사 붙은 산출물도 무시).
- `scripts/normalize_odl.py`: 기본 출력 `_fused.md` → `_fused_v3_opendataloader.md`.
- README·gotchas·postprocess 참조 일괄 갱신.

## [3.17] - 2026-06-28

### 변경
- **Gemini·Mistral `latest` 모델 업데이트 재평가**(대표 PDF 3종: 텍스트PDF 187p·스캔양식 15p·수기 22p). 모델 버전: Gemini `2.5-flash`→**`3.5-flash`(thinking)**, Mistral OCR `2512`→**`ocr-4`**.
- `parsers/gemini_parse.py`: 기본 `thinking_budget=0` + `max_output_tokens=65536`으로 **장문 요약화 방지**(thinking이 켜지면 장문을 전사 대신 요약해 본문을 버리고 완결 위장). `text=None` 가드 + 1회 재시도, MAX_TOKENS 경고 추가. **`--thinking` 옵션** 신설(체크박스·한글이름 등 소형 보조 패치용으로 thinking 활성화).
- **Mistral ocr-4 헤딩 생성 추가**: 텍스트PDF에서 헤딩 5→76, 187p·17섹션 완전 전사. LlamaParse v2 크레딧 부족 시 ODL과 함께 폴백 Primary 후보로 격상(노이즈 strip + 글자 드리프트 패치 전제). SKILL.md 파서 비교표·tier-rules 반영.
- **Gemini 보조 역할 격상**: 체크박스(F→A)·한글이름·텍스트 패치 1순위 보조(thinking ON). 단 장문 Primary 금지, 본문 verbatim 정본 부적합(철자 무단교정 신규 회귀).

### 수정
- 부록 J의 "Mistral `carring→calling` 과잉교정" 사례를 **Gemini 오독으로 정정**(학생이 실제 `calling` 표기). 평가 보고서 부록 M에 반영.
- 정본 `02_파싱결과/…fused.md`(스캔 양식 검증본)에 혼입된 구 Gemini 2.5 자가생성 "요약 통계" 117줄 제거.
- gotchas.md: Gemini thinking 요약화·`text=None` 함정, 한글 파일명 NFC/NFD 정규화 함정, 백그라운드 `&`+`cd` 함정 추가.

> 결론: **Primary 순위는 대부분 유지**(텍스트PDF=LlamaParse v2, 스캔양식=Upstage+Mistral, 수기=GV+Opus 캐스케이드). 변화는 Gemini 장문 Primary 금지 명문화 + 보조 역할 재배치, Mistral 폴백 가치 상승. 상세: 비교평가 보고서 부록 M.

## [3.16] - 2026-06-25

### 변경
- LlamaParse v2 출력에 남는 `<page_number>...</page_number>` 태그를 제거하는 후처리 패턴 추가.
- medium 티어 다건 동시 파싱 시 rate limit(429) 회피를 위해 Upstage 동시 호출을 6~8건 이하로 권장.

## [3.15] - 2026-06-23

### 추가
- `score_transcription.py`: 정본 대비 CER/WER 정량 채점 스크립트(모델·방법 calibration용).
- `extract_vision_drafts.py`: 손글씨 캐스케이드 2단계용 Vision 드래프트 추출 스크립트.

### 변경
- 손글씨 캐스케이드 모델 순위를 "Opus ≈ Sonnet"에서 "Opus ≥ Sonnet"로 갱신(정량 검증 반영). repair 프롬프트에 클린 출력 규칙(주석 금지, 판독불가 `?`, 백지 빈 본문) 추가.

## [3.14] - 2026-06-17

### 추가
- `references/handwriting-cascade.md`: 손글씨 충실 전사 최고 방법(Vision → Claude 비전 캐스케이드) 워크플로우와 repair 프롬프트, 모델 비교, 속도.

## [3.13] - 2026-06-14

### 추가
- `parsers/gvision_parse.py`: Google Vision 손글씨 파서. 단어별 confidence를 제공해 오기를 보존하고 검증 표적을 좁힘.
- `scripts/diff_fidelity.py`: LLM 파서와 OCR 출력을 토큰 정렬해 환각·교정·오독 후보를 페이지별 육안 검증 표적으로 출력.
- `references/handwriting-ocr-engines.md`: 손글씨 충실 전사용 OCR 엔진 비교 서베이.

## [3.12] - 2026-06-12

### 추가
- 워크플로우에 Step 9(사후 절차) 신설: 매 작업 후 추가 교차검증 필요성을 5개 트리거로 점검.

## [3.11] - 2026-06-12

### 변경
- 비한국어·혼합 언어 자료에 Mistral 3자 교차검증을 적용하는 조건 정밀화(스캔 + 라틴계 외국어 조합에서 가치 큼, 숨김·가림 텍스트 의심 문서에는 Mistral 단독 금지).

## [3.10] - 2026-06-11

### 추가
- 손글씨 답안 등 충실 전사가 중요한 스캔 문서용 티어 규칙. 다페이지 시각 판독을 서브에이전트에 위임하는 패턴(이미지 누적 한도 회피).

## [3.9] - 2026-06-06

### 추가
- `parsers/hwpx_local_parse.py`: 로컬·무료 HWPX 파서. 자가검증 3종(단어 recall, 글자 멀티셋 recall, 객관식 마커 보존) 내장.

### 변경
- HWPX Primary를 유료 클라우드에서 무료 로컬(`hwpx_local`)로 전환. 이미지 내 텍스트·레이아웃·경고 시에만 Upstage 폴백. 변환 엔진을 독립 패키지 `hwpx-tomd` 단일 소스로 통일.

## [3.8.1] - 2026-06-02

### 변경
- Corepin을 "독자 파싱 엔진"이 아니라 형식별 OSS 백엔드 라우터로 정정. 스캔 양식에서 표·헤딩 구조가 소실되어 해당 티어 Primary로 부적합함을 확인(보조·비교용으로 유지).

## [3.8] - 2026-06-01

### 추가
- `parsers/corepin_parse.py`: 다포맷 단일 API 파서(텍스트 PDF, HWP/HWPX, Office, 스캔 OCR). 한국어 필터 SLM 포함.

## [3.7] - 2026-05-21

### 변경
- HWPX를 기본 티어 표에 정식 편입. 출판사 워크시트·시험지급 HWPX는 처음부터 docparse 경로로 직행(2단 레이아웃 선택지 누락 회피).

## [3.6] - 2026-05-14

### 변경
- OpenDataLoader 가드 강화: 텍스트 레이어가 있어도 출판 임베딩 폰트의 글리프 매핑이 깨지면 본문 숫자가 누락될 수 있으므로, ODL을 Primary로 채택하기 전 본문 숫자를 다른 파서와 대조하도록 명시.
- 학술·연구 보고서에서 LlamaParse v2 헤딩 위계가 불안정한 패턴과 챕터 표지 정리 규칙 추가.

## [3.5] - 2026-05-14

### 변경
- SKILL.md 본체를 핵심 워크플로우 + 의사결정 표로 축소하고, 상세 노하우를 `references/`로 분리(progressive disclosure). `tier-rules.md`, `postprocess.md`, `gotchas.md` 신설.

## [3.4] - 2026-05-14

### 변경
- `llamaparse_parse.py`의 custom prompt 주입 옵션을 `--instructions` 단일 이름으로 명확화.
- 분할·합본 챕터에서 H1이 2~4행으로 쪼개지는 패턴과 헤더 inline 디자인 아이콘 alt 정리 규칙 추가.

## [3.3] - 2026-05-14

### 변경
- `generate_alt_text.py`의 stdout 인코딩을 UTF-8로 강제해 Windows cp949 환경에서의 정지 방지.
- 짧고 무의미한 alt를 Gemini로 풍부화(접근성). 연속 챕터 H1 미니 TOC 제거 규칙 추가.

## [3.2] - 2026-05-14

### 추가
- 인포그래픽이 풍부한 인쇄용 책자의 잔여 노이즈 정리 7종 패턴.
- PyMuPDF 렌더링 + Gemini로 페이지별 한국어 상세 alt를 생성해 본문에 inline 보존(시각장애 사용자 접근성).
- `llamaparse_parse.py --instructions`로 agentic custom prompt 주입(접근성 우선 템플릿 포함).

## [3.1] - 2026-04-27

### 추가
- 시험지·고사 원안·평가지 카테고리 신설: 페이지 수와 무관하게 다파서 교차검증 필수(Gemini + Upstage + ODL + 정답표 매칭).
- 20페이지 이하 PDF에서 Claude의 시각 렌더링을 교차검증 최종 결정자로 활용.

## [3.0] - 2026-04-10

### 변경
- 전 티어 Primary를 LlamaParse v2 agentic으로 전환. Primary + Patch 퓨전(갭만 보충) 확립.
- 구 Semtools v1 제거(v2가 완전 대체). OpenDataLoader는 교차검증 + 크레딧 부족 시 폴백으로 재배치.

## [2.1] - 2026-04-07

### 변경
- 스캔 양식 표는 Gemini를 Primary·교차검증에 사용 금지. 동일 양식 다수는 합본 대신 개별 파싱 권장.

## [2.0] - 2026-03

### 변경
- 항상 3~4종을 모두 돌리던 방식에서, 사전 진단으로 티어별 1~4종을 고르는 적응형 선택으로 전환. 퓨전을 전체 재작성에서 Primary + Patch로 변경. OpenDataLoader 도입.

## [1.0]

### 추가
- 초기 버전. 다중 파서를 모두 실행한 뒤 결과를 전체 재작성으로 합치는 방식.
