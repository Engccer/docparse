# HWPX·HWP 파싱 상세

`assess_document.py`가 `format: "hwpx"` 또는 `"hwp"`를 낼 때 읽는다. 요지는 SKILL.md 기본 티어 표의 hwpx 행과 Step 3 hwpx 예시다.

## 목차

- HWPX 티어 · HWPX 결정론 보강 · 초안 HWP + 인쇄 PDF 하이브리드 · Upstage로 교차/대체하는 경우 · hwpx-tomd 미설치·암호화 · hwpx_local 변환 결함은 공유 엔진(hwpx-tomd) 소관 · HWP/HWPX 파싱 세부 절차

## HWPX 티어

`assess_document.py`가 `format: "hwpx"`로 진단 시 **로컬·무료 파서 `hwpx_local_parse.py`(hwpx-tomd 엔진)를 먼저** 쓴다. 글상자(drawText) reading-order 수집, `<hp:t>` tail 보존(객관식 선택지 ②③⑤ 누락 방지), 표 cellAddr/cellSpan 그리드 배치(세로·가로 병합 보존)가 검증됐다. 변환 후 자가검증 3종(단어 recall + 글자 멀티셋 recall + 객관식 마커 보존 가드)이 조용한 누락을 막는다.

*근거: 실문서 33종에서 원본 `<hp:t>` 대비 글자 멀티셋 손실 0·객관식 마커 손실 0(문자·마커 단위 완벽 보존), 2026-06-06*

## HWPX 결정론 보강

hwpx-tomd는 본문·표를 정확히 옮기지만 제목 수준·취소선·글자색·쪽 번호를 버린다. 보고서류(개요 스타일로 제목을 잡은 문서, 서식이 의미를 갖는 조사지, 검수자가 원본 쪽수로 대조하는 문서)는 변환 직후 `scripts/hwpx_enrich.py`로 보강한다.

```bash
python <스킬루트>/scripts/hwpx_enrich.py --hwpx <원본.hwpx> --md <_hwpxlocal.md> --out <_enriched.md> \
    --pdf <인쇄 PDF> --heading "개요 2:2,개요 3:3,…" --mark-color 0000FF
```

- 제목은 `header.xml`의 style 이름(「개요 1~10」, 부 제목은 머리말 스타일)→레벨 매핑, 서식은 `charPr`의 `strikeout`·`textColor`, 쪽 번호는 PDF 쪽 텍스트(pdftotext, poppler 필요)와의 전역 단조 정렬(LIS)로 잡는다(kordoc 등의 추정 페이지네이션은 인쇄본과 어긋나므로 쓰지 않는다).
- 쪽 주석은 기본으로 쪽이 바뀐 뒤 처음 만나는 제목 앞에만 붙는다. `apply_corrections.py`로 원본 쪽을 한정해 치환하려면 `--page-comment-every`를 붙여 쪽이 바뀐 뒤 처음 만나는 표 밖 본문 줄 앞에도 주석을 남긴다.
- 원본과 달라지는 수정(오탈자·개인정보)은 `apply_corrections.py`로 CSV 경유만.
- **kordoc·pyhwp는 보조·대조용**: kordoc JSON은 표별 rowSpan/colSpan 명세와 장 제목이 유용하지만 쪽 번호는 자체 추정이고, pyhwp `hwp5proc xml`·한컴 COM 변환본은 **취소선(`line_through`/strikeout)을 표지 제목까지 켜진 것으로 읽어 신뢰할 수 없다**.
- 표 병합은 `hwpx_local_parse.py <파일.hwpx> --merge-fill`로 세로·가로 병합값을 덮인 칸에 반복 기입한다(빈 칸이 「병합」인지 「원래 빈 셀」인지 독자와 RAG가 구분할 수 없기 때문. 병합셀 하나에 항목 여러 개가 들어 있으면 셀째로 반복되므로 1:1 대응 날조가 생기지 않는다). 엔진 CLI(`hwpx-tomd --merge-fill`)를 직접 부르면 래퍼의 자가검증(누락 의심 시 출력 안 함)을 거치지 않는다.

*근거: 2023 보고서 실측: hwp2hwpx HWPX의 charPr 취소선 10런이 인쇄본과 정확히 일치, COM 21,680런·pyhwp 43,616런은 오판. 보강 실측: (2026-08-28, 554쪽 HWP 보고서에서 제목 301·서식 런 729·쪽 주석 134 실측)*

## 초안 HWP + 인쇄 PDF 하이브리드

편집 원본이 인쇄본과 판본이 다르면(초안 HWP가 회수된 경우) HWP를 내용 정본으로 쓰지 말고 **구조는 HWP, 내용은 PDF**로 나눈다.

1. 본문·표는 hwpx-tomd, 제목은 `hwpx_enrich.py --title-table '^\d{1,2}$:2'`(인쇄 책자는 절 제목을 `| 1 | 제목 |` 두 칸 표로 디자인한다)와 `--heading-regex`의 번호 패턴(수준은 문서마다 다르므로 상수로 박는다; `'^□ :+1'`처럼 직전 제목 기준 상대 수준을 쓰면 같은 규칙의 형제는 같은 수준, H1은 부모로 삼지 않는다)으로 세운다.
   - ⚠ 부 제목(`머-우` 등 머리말 스타일)은 **구역 머리말이라 구역 나누기 위치(본문 중간)에 찍힌다** — 간지 레이아웃 표(로마 숫자 행)에서 H1을 만들고 머리말 유래 H1은 지운다(문서 고유 후처리라 이 저장소에는 일반 스크립트가 없다. `hwpx_enrich.py --title-table`·`--heading-regex`로 세운 뒤 남는 머리말 H1을 지우는 짧은 스크립트를 작업 폴더에 둔다).
2. PDF 대조는 어절 차집합 + 부분 문자열 필터로 하고(작업 폴더 스크립트), 남은 어휘로 **문장 대응표**를 만들어 문구 수정은 `apply_corrections.py` CSV로, 최종본 추가분은 앵커 삽입 명세(앵커가 0회 또는 2회 이상 맞으면 중단)로 반영한다.
3. 「PDF에만 있음」이 곧 추가분은 아니다: HWP에서 **그림**(BMP 흐름도·한도 표)이던 것이 인쇄본에서 텍스트로 재조판된 경우가 많으므로 이미지 배치 위치와 PDF 텍스트를 먼저 대조한다(`--image-dir` 추출 목록 + 직전 줄 문맥).
4. 심볼 글꼴 PUA 글리프(U+F0E8 →, U+F003B ↓, U+F0FE □)는 텍스트로는 빈 칸이라 표 앵커·검색이 어긋나므로 후처리에서 치환한다.

*근거: 인쇄 책자 3종 실측(2026-08-28)*

## Upstage로 교차/대체하는 경우

1. **이미지 안의 텍스트**(제목·도표·캡션 등)가 중요한 문서. hwpx_local은 이미지 텍스트를 추출하지 못하고 본문에 이미지가 있으면 경고한다(OCR은 Upstage 영역).
2. **시각적 배치 재현**이 중요한 문서(고사 원안 레이아웃 등). 글상자는 anchor 기반 reading-order 근사이고 중첩표는 텍스트로 평탄화된다.
3. hwpx_local의 **recall·마커 경고**가 뜨는 문서. 이 경우 `upstage_parse.py`를 함께 돌려 대조한다.

## hwpx-tomd 미설치·암호화

hwpx_local은 `hwpx-tomd` 패키지(`pip install hwpx-tomd`, PyPI·GitHub `Engccer/hwpx-tomd` 공개)에 의존한다. 미설치 디바이스에서는 hwpx_local이 설치 안내를 출력하며 동작하지 않으므로 **Upstage 단독으로 폴백**한다. 암호화(AES) 배포본은 hwpx_local이 자동 감지해 안내하며 Upstage도 파싱 불가다(한컴에서 암호를 제거해 다시 저장한 뒤 변환한다). HWPX **편집**(`--set-cell`/`--find` 등)과 HWP→HWPX 변환은 `hwpx-automation` 스킬을 쓴다.

## hwpx_local 변환 결함은 공유 엔진(hwpx-tomd) 소관

hwpx_local의 변환 누락·표 정렬 붕괴·마커 손실을 발견하면, 이는 docparse 파서 스크립트가 아니라 **`hwpx_local_parse.py`와 `hwpx-automation`의 `hwpx_edit.py --to-md`가 공유하는 변환 엔진 `hwpx-tomd`(`core.py`)의 결함**이다(다른 PDF 파서들과 달리 hwpx_local만 이 외부 엔진을 공유한다). 엔진은 PyPI·GitHub(Engccer/hwpx-tomd)로 공개돼 있고 **GitHub가 단일 진실 원천(SSoT)**이다.

- 처리 절차(엔진 repo의 `CONTRIBUTING.md`가 정본): `hwpx-tomd`의 `tests/test_hwpx_tomd.py`에 **실패하는 회귀 테스트를 먼저 추가** → `core.py` 수정 → 버전(`_version.py`) bump → `git push` → PyPI publish.
- 엔진을 editable로 설치(`pip install -e`)한 환경에서는 수정이 즉시 반영되고, PyPI 설치만 된 환경에서는 `pip install -U hwpx-tomd`로 받는다.
- 반대로 변환이 아닌 노이즈 필터링·티어 선택·퓨전 등 docparse 고유 로직의 개선은 이 저장소에서 처리하고, 사용자에게 영향이 있으면 `CHANGELOG.md`에 기록한다.

## HWP/HWPX 파싱 세부 절차

*근거: **단계마다 다르다.** 1~2단계(hwpx-tomd 변환) n=33(실문서 33종 글자 멀티셋 손실 0·마커 손실 0, 2026-06-06) / 4~5단계(`hwpx_enrich` 보강·kordoc 대조) **n=1**(554쪽 보고서, 2026-08-28) / 6단계는 변환 실패 대응이라 문서 수 개념 없음 / 3·7단계는 라우팅. **절 전체를 n=33으로 읽지 말 것** — 가장 두꺼운 근거는 변환 정확도에만 해당한다*

1. HWP → `hwpx-automation` 스킬의 `convert/hwp2hwpx.bat <입력.hwp>`(Windows) 또는 `convert/hwp2hwpx.sh`(macOS/Linux)로 HWPX 변환 (Java, 서식 보존).
2. HWPX → `parsers/hwpx_local_parse.py <파일.hwpx>`로 마크다운 변환(출력 `_hwpxlocal.md`). 긴 지문이 셀 안에 있으면 `--cell-br`, 병합값 반복 기입은 `--merge-fill`.
3. 이미지 경고·recall/마커 경고가 뜨거나 시각적 배치 재현이 중요하면 Upstage 추가 실행하여 비교(위 「Upstage로 교차/대체하는 경우」).
4. 보고서류는 변환 직후 `scripts/hwpx_enrich.py`로 제목(개요 스타일)·취소선·글자색·인쇄 PDF 쪽 번호를 보강한다(위 「HWPX 결정론 보강」). 취소선·글자색의 정본은 **hwp2hwpx HWPX의 `charPr`**이며 pyhwp XML·한컴 COM 변환본의 strikeout은 오판이 확인돼 쓰지 않는다.
5. kordoc(`npx --yes --package kordoc --package pdfjs-dist kordoc <hwp> --format json`)은 HWP를 직접 읽어 표별 rowSpan/colSpan 명세·장 제목·글꼴 크기를 JSON으로 주므로 **보조 메타·대조용**으로 유용하다(2026-08-28 554쪽 보고서에서 본문 글자 hwpx_local과 동일, 누락 1자). 단 쪽 번호는 자체 추정(495쪽 vs 인쇄 554쪽)이라 인쇄본 쪽수로 쓰지 않는다. 2026-03의 표 중심 문서 파싱 실패 사례가 있어 Primary로는 여전히 비권장.
6. hwp2hwpx가 예외로 죽는 HWP(`extendControl IndexOutOfBounds`=컨트롤 문자 수 불일치, `EmptyStackException`=필드 짝 불일치)는 hwpx-automation의 패치 JAR로 재시도하고, 그래도 안 되면 Windows 한컴 COM(`hwpx_com.py --from-hwp`, SSH에서는 `schtasks /IT` 경유)으로 변환한다.
7. HWPX 편집(`--set-cell`/`--find` 등)은 docparse가 아니라 `hwpx-automation` 스킬의 `hwpx_edit.py`를 쓴다(docparse는 읽기 전용).
