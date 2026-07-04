---
name: docparse
description: >
  적응형 문서 파싱 워크플로우. 문서를 사전 진단하여 최적의 파서 조합을 선택하고,
  Primary+Patch 방식으로 효율적으로 퓨전하여 최고 품질의 단일 마크다운을 생성.
  트리거: (1) 문서를 최고 품질로 파싱하고 싶을 때 (2) /docparse 명령 사용 시
  (3) 여러 파서 결과를 조합/퓨전하려 할 때 (4) PDF, 이미지, HWP, DOCX 등 문서에서
  텍스트를 추출할 때
---

# DocParse v3: 적응형 파싱 + Primary+Patch 퓨전

문서를 사전 진단 → 최적 파서 조합 선택 → Primary+Patch 퓨전으로 효율적 고품질 마크다운 생성. LlamaParse v2 (agentic 티어)가 medium~xlarge Primary.

## 사용법

```
/docparse                       # 현재 디렉토리에서 파일 자동 탐색
/docparse input.pdf             # 파일 지정
/docparse input.pdf --lang en   # 비한국어 문서
```

**인수 파싱**: 공백 분리 → `--lang <값>`을 언어 코드로 추출(기본 `ko`) → 나머지 첫 토큰을 파일 경로로 → 경로 없으면 현재 디렉토리에서 지원 확장자 자동 탐색(Glob).

## 패키지 구조

자기 완결적(self-contained) 패키지. `~/.claude/skills/docparse` 심링크가 가리키는 폴더 하나만 동기화하면 모든 디바이스에서 완전 동작. 실행 시 이 경로를 `<스킬루트>`로 부른다.

### 파서 (`parsers/`)

| 스크립트 | 출력 | API | 비고 |
|---------|------|-----|------|
| `hwpx_local_parse.py` | `_hwpxlocal.md` | 없음 (로컬) | **HWPX 전용·무료·오프라인**. hwpx-tomd 패키지 엔진(글상자·tail·표 병합 보존, 자가검증 3종). `pip install hwpx-tomd` 필요. 이미지 내 텍스트는 범위 밖(경고). HWP는 hwp2hwpx 변환 후 입력 |
| `upstage_parse.py` | `_upstage.md` | UPSTAGE_API_KEY | 기준선, 노이즈 필터링 최강, 완전성 최고 |
| `gemini_parse.py` | `_gemini.md` | GEMINI_API_KEY | `gemini-3.5-flash`(thinking 모델). 텍스트 품질·체크박스·한글이름 최상이나 **장문에서 요약화 위험**. 기본 `thinking_budget=0`(요약화 방지·충실 전사), `--thinking`으로 켜면 체크박스·정밀 판독↑(소형 보조용). small(≤15p)만 Primary |
| `llamaparse_parse.py` | `_llamaparse.md` | LLAMAPARSE_API_KEY | **v2 agentic 기본**. 표 열 정확도·OCR 우수. 10크레딧/p |
| `mistral_parse.py` | `_mistral.md` | MISTRAL_API_KEY | `mistral-ocr-4`. 대용량 완전성 + **헤딩 구조 생성(ocr-4 신규)**, 교차 검증용. 노이즈·OCR 글자 드리프트·수기 과잉교정 잔존 |
| `opendataloader_parse.py` | `_opendataloader.md` | 없음 (로컬) | Java 필요, PDF 전용, 텍스트 레이어 필수 |
| `corepin_parse.py` | `_corepin.md` | COREPIN_API_KEY | AI3 OSS 엔진 라우터(텍스트PDF→opendataloader, HWP/HWPX→kordoc, Office→markitdown, **스캔→AI3 자체 OCR**) + 한국어 필터 SLM. 18종 단일 API, 장당 2원. **스캔 양식에서 표 구조 소실 검증됨** → Primary 부적합, 보조/비교용 |
| `gvision_parse.py` | `_gvision.md` | GOOGLE_VISION_API_KEY **또는** GV_TOKEN+GV_PROJECT | **비-LLM OCR + 단어별 confidence**. 수기 손글씨 답안 등 오기 보존 critical 문서 전용. 자동교정·인명환각 없이 literal 추출, 저신뢰(<0.90) 단어를 페이지별로 표기 → 시각 판독 표적 자동 생성. PDF는 PyMuPDF로 렌더 후 페이지별 호출. 무료 1,000p/월. **calibration 실증(2026-06-14)**. reading order·체크박스는 약점(v2 병행) |

### 스크립트 (`scripts/`)

| 스크립트 | 용도 |
|---------|------|
| `check_env.py` | 파서별 의존 패키지·API 키 준비 상태 + 키 발급 URL 점검 (첫 실행 시·읽기 전용) |
| `assess_document.py` | 문서 사전 진단 (페이지 수·텍스트 레이어·티어·파서 추천 JSON) |
| `compare_outputs.py` | 파서 출력 비교 (heading 갭·표 수·퓨전 전략) |
| `normalize_odl.py` | ODL 출력 자동 정리 (페이지 구분자·h6 정규화·heading 승격·빈 줄 압축) |
| `generate_alt_text.py` | 시각장애인 접근성 alt text 자동 생성 (PyMuPDF + Gemini Vision, 한국어 상세화) |
| `diff_fidelity.py` | 손글씨 파이프라인 ③단계: LLM 파서 ↔ OCR(gvision) 토큰 정렬로 **발산 토큰**(환각/교정/오독 후보) + OCR 저신뢰 단어를 합쳐 페이지별 "육안 검증 표적" 생성 (전수 → 표적) |
| `extract_vision_drafts.py` | 캐스케이드 ②단계: `_gvision.md`에서 페이지별 영어 드래프트(라틴 포함·한글 미포함 라인)+저신뢰 목록을 `draft_pNN.txt`로 추출. Claude repair 입력 |
| `score_transcription.py` | 손글씨/OCR 전사 **정량 채점**: 정본 대비 후보들의 CER·WER를 항목별·micro/macro 집계(편집 주석 대칭 제거·백지 집계 제외). 모델·방법 calibration용 (2026-06-23 토너먼트에서 정립) |

### 참조 (`references/`)

| 파일 | 트리거 |
|------|--------|
| `tier-rules.md` | 스캔/수기/시험지/합본 PDF 등 티어 외 보정 규칙이 필요할 때 |
| `handwriting-cascade.md` | **손글씨 충실 전사 최고 방법**: Vision→Claude(Opus) 캐스케이드가 챔피언(정본 대조 ~98.2%). 모델 비교(단독: Opus>Sonnet +1.0%p / 캐스케이드: +0.3%p, Gemma·Haiku 탈락)·클린 repair 프롬프트·속도. 5-subset 정성 + 3반 토너먼트 CER/WER 정량(2026-06-23) |
| `handwriting-ocr-engines.md` | 손글씨 위주 스캔 문서 충실 전사용 OCR 엔진 선택(Vision·Azure·CLOVA·TrOCR·Tesseract 등 비교·언어·PII·비용) |
| `postprocess.md` | LlamaParse v2 후처리 정규식·ODL 자동 정리·Step 7 최종 노이즈 정리 |
| `gotchas.md` | 주의사항·에러 처리·설치 |
| `fusion-prompt.md` | full fusion 상세 지침 (대규모 재작성 시) |
| `custom-prompts/accessible.txt` | `llamaparse_parse.py --instructions`에 주입할 접근성 우선 파싱 지시 |

## 파서별 특성 한눈 비교

| 파서 | 종합 | 완전성 | 텍스트 | Heading | 표 | 제한 |
|------|------|-------|--------|---------|----|------|
| **hwpx_local** (HWPX) | A | A+ (글자·마커 100%) | A | B (원문 구조 그대로) | A (cellAddr/cellSpan 그리드) | HWPX 전용, 이미지 내 텍스트 불가, 레이아웃은 근사 |
| **Upstage** | A | A+ (100%) | A | A | A- | 동기 100p 제한, 스캔 OCR 단어 분절 |
| **LlamaParse v2** | A | A | A | A+ | **A+** | 10크레딧/p, 스캔 수기 양식 열 이동 1건 |
| **OpenDataLoader** | A- | A+ (100%) | B+ | B (h6 경향) | A | PDF·텍스트 레이어 전용, 이미지 설명 없음 |
| **Mistral** | B+ | A+ (100%) | A- | **B+ (ocr-4 헤딩 생성)** | A- | 노이즈 후처리 필수, OCR 글자 드리프트, 수기 과잉교정 |
| **Gemini** (3.5/thinking) | B-(≤15p) | 소형 A / **장문 요약화 F** | A+ | A+ | A+ 포맷 / C 스캔 열(시프트 잔존) | **장문 Primary 금지**(요약화), ≤15p만. 체크박스·한글이름 A(thinking ON 보조). 기본 `thinking_budget=0` |
| **Google Vision** (수기) | A-(수기 전용) | A(손글씨) | **A (오기 보존)** | F(미생성) | C(미지원) | **단어별 confidence 제공(평균 0.95+, 저신뢰 ~7%·잘 calibrated)**. 수기 오기 보존·환각 0. reading order 흐트러짐·체크박스 판정 불안정·클라우드 PII |

## 실행 워크플로우

### Step 0: 환경 점검 (첫 실행 또는 키·의존성 의심 시)

```bash
python "<스킬루트>/scripts/check_env.py"
```

파서별 의존 패키지·API 키 준비 상태와 키 발급 URL을 한 번에 출력한다(읽기 전용, 아무것도 설치하지 않음). 처음 클론한 환경이거나 특정 파서가 키·패키지 누락으로 실패하면 먼저 실행해 무엇을 설치·설정할지 확인한다. 무료 로컬 파서(hwpx_local·opendataloader)는 키 없이 바로 쓸 수 있다. 매 작업마다 필요한 절차는 아니므로, 환경이 준비된 뒤에는 건너뛴다.

### Step 1: 사전 진단

```bash
python "<스킬루트>/scripts/assess_document.py" "<파일경로>"
```

JSON에서 `tier`, `pages`, `has_text_layer`, `format` 확인 → 티어별 파서 전략 결정.

### Step 2: 적응형 파서 선택

#### 기본 티어 표

| 티어 | 조건 | 파서 전략 | Primary |
|------|------|----------|---------|
| **hwpx** | HWPX 파일 | hwpx_local(로컬·무료) 우선, 이미지·레이아웃 중요 시 Upstage 교차/대체 | hwpx_local |
| **small** | PDF ≤15p | Gemini 단독 | Gemini |
| **medium** | PDF 16~60p | LlamaParse v2 + Upstage | LlamaParse v2 |
| **large** | PDF 61~100p | LlamaParse v2 + ODL | LlamaParse v2 |
| **xlarge** | PDF 101p+ | LlamaParse v2 + ODL | LlamaParse v2 |

**HWPX 티어**: `assess_document.py`가 `format: "hwpx"`로 진단 시 **로컬·무료 파서 `hwpx_local_parse.py`(hwpx-tomd 엔진)를 먼저** 쓴다. 글상자(drawText) reading-order 수집, `<hp:t>` tail 보존(객관식 선택지 ②③⑤ 누락 방지), 표 cellAddr/cellSpan 그리드 배치(세로·가로 병합 보존)가 검증됐다. 실문서 33종에서 원본 `<hp:t>` 대비 글자 멀티셋 손실 0·객관식 마커 손실 0(문자·마커 단위 완벽 보존)이고, 변환 후 자가검증 3종(단어 recall + 글자 멀티셋 recall + 객관식 마커 보존 가드)이 조용한 누락을 막는다(2026-06-06).

**Upstage로 교차/대체하는 경우**: (1) **이미지 안의 텍스트**(제목·도표·캡션 등)가 중요한 문서. hwpx_local은 이미지 텍스트를 추출하지 못하고 본문에 이미지가 있으면 경고한다(OCR은 Upstage 영역). (2) **시각적 배치 재현**이 중요한 문서(고사 원안 레이아웃 등). 글상자는 anchor 기반 reading-order 근사이고 중첩표는 텍스트로 평탄화된다. (3) hwpx_local의 **recall·마커 경고**가 뜨는 문서. 이 경우 `upstage_parse.py`를 함께 돌려 대조한다.

**self-contained 단서**: hwpx_local은 `hwpx-tomd` 패키지(`pip install hwpx-tomd`, PyPI·GitHub `Engccer/hwpx-tomd` 공개)에 의존한다. 미설치 디바이스에서는 hwpx_local이 설치 안내를 출력하며 동작하지 않으므로 **Upstage 단독으로 폴백**한다. 암호화(AES) 배포본은 hwpx_local이 자동 감지해 안내하며 Upstage도 파싱 불가다. HWPX **편집**(`--set-cell`/`--find` 등)과 HWP→HWPX 변환은 `hwpx-automation` 스킬을 쓴다.

HWP는 먼저 `hwpx-automation` 스킬의 `hwp2hwpx.bat`로 HWPX 변환 후 진입. 다른 비PDF 포맷(DOCX·PPTX·XLSX 등)은 미검증.

**hwpx_local 변환 결함은 공유 엔진(hwpx-tomd) 소관**: hwpx_local의 변환 누락·표 정렬 붕괴·마커 손실을 발견하면, 이는 docparse 파서 스크립트가 아니라 **`hwpx_local_parse.py`와 `hwpx-automation`의 `hwpx_edit.py --to-md`가 공유하는 변환 엔진 `hwpx-tomd`(`core.py`)의 결함**이다(다른 PDF 파서들과 달리 hwpx_local만 이 외부 엔진을 공유한다). 엔진은 PyPI·GitHub(Engccer/hwpx-tomd)로 공개돼 있고 **GitHub가 단일 진실 원천(SSoT)**이다. 처리 절차(엔진 repo의 `CONTRIBUTING.md`가 정본): `hwpx-tomd`의 `tests/test_hwpx_tomd.py`에 **실패하는 회귀 테스트를 먼저 추가** → `core.py` 수정 → 버전(`_version.py`) bump → `git push` → PyPI publish. 엔진을 editable로 설치(`pip install -e`)한 환경에서는 수정이 즉시 반영되고, PyPI 설치만 된 환경에서는 `pip install -U hwpx-tomd`로 받는다. 반대로 변환이 아닌 노이즈 필터링·티어 선택·퓨전 등 docparse 고유 로직의 개선은 이 저장소에서 처리하고, 사용자에게 영향이 있으면 `CHANGELOG.md`에 기록한다.

**Primary 선택 원칙**: 자동화로 교정 불가능한 결함이 적은 파서를 Primary로. LlamaParse v2가 medium~xlarge 최적 (목차 정리, 표 열 정확, 노이즈 0건, LaTeX 0건). 크레딧 부족 시 ODL Primary + Upstage 교차검증으로 폴백. **Mistral ocr-4는 헤딩 구조 생성이 추가돼(2026-06-28) 텍스트PDF 폴백 Primary 후보로 격상**(187p·17섹션 완전 전사 검증)되나, 노이즈 185건·OCR 글자 드리프트(`장애전형→장애인형`) 후처리가 전제다.

**small 티어 Gemini 주의 (2026-06-28)**: `gemini-flash-latest`는 thinking 모델 `gemini-3.5-flash`다. thinking이 켜지면 **장문(≳20p)에서 전사 대신 요약으로 빠져** 본문을 조용히 버리고 완결 문서처럼 위장한다(187p 실측, 부록 M). `gemini_parse.py`는 이를 막기 위해 **기본 `thinking_budget=0` + `max_output_tokens=65536`**으로 충실 전사한다. **Gemini를 장문 Primary로 쓰지 말 것**(small ≤15p만). 단 thinking을 끄면 수기 자필 체크박스 판독이 약해지므로, 체크박스·한글이름 등 정밀 판독이 필요한 **보조 패치**에는 `gemini_parse.py <파일> --thinking`으로 켜서 별도 호출한다.

#### 보정 규칙 (티어 결정 후 적용)

아래 케이스에 해당하면 `references/tier-rules.md` 적용:

- 텍스트 레이어 없음 (스캔/이미지 PDF)
- 스캔 문서 + 표에 숫자 데이터 (신청서·양식·집계표)
- 동일 양식 다수 합본 PDF
- 시험지·고사 원안·평가지 (옵션 텍스트 critical)
- 수기 학생 답안 합본 (자유 서술 손글씨 + 체크박스, 오기 보존 critical, v2 단어 환각 경계, 전 페이지 시각 판독 필수)
- 영어 비율 ≥50% / 정형화 양식 (Mistral Primary 후보)
- 의무기록·법률문서·계약서 (정확성 critical, 3자 교차)
- 비PDF 포맷 중 HWPX 외 (DOCX·PPTX·XLSX·이미지): 검증 전, tier-rules 참조. HWPX는 기본 티어 표의 `hwpx` 행으로 처리
- ≤20p 소형 PDF (Read 시각 렌더링 = ground truth)

### Step 3: 파서 실행

선택된 파서만 병렬 실행. xlarge는 `timeout 600`, 그 외 `timeout 300`. `< /dev/null`로 대화형 프롬프트 방지.

```bash
# medium 티어 예
timeout 300 python <스킬루트>/parsers/llamaparse_parse.py "<파일경로>" < /dev/null &
timeout 300 python <스킬루트>/parsers/upstage_parse.py "<파일경로>" < /dev/null &
wait
```

```bash
# xlarge 티어 예
timeout 600 python <스킬루트>/parsers/llamaparse_parse.py "<파일경로>" < /dev/null &
timeout 300 python <스킬루트>/parsers/opendataloader_parse.py "<파일경로>" < /dev/null &
wait
```

```bash
# hwpx 티어 예 (로컬·무료 우선; 긴 지문이 셀 안에 있으면 --cell-br)
timeout 300 python <스킬루트>/parsers/hwpx_local_parse.py "<파일.hwpx>" < /dev/null
# 이미지 경고·recall 경고가 뜨거나 레이아웃이 중요하면 Upstage로 교차검증
timeout 300 python <스킬루트>/parsers/upstage_parse.py "<파일.hwpx>" < /dev/null
```

**접근성 우선 파싱** (장애인 안내자료·시각장애인 사용자 문서)에서는 `--instructions <스킬루트>/references/custom-prompts/accessible.txt`를 붙여 v2 `agentic_options.custom_prompt`를 주입한다. **옵션명은 `--instructions` 단 하나뿐**, 다른 이름(`--custom-prompt-file`, `--prompt` 등)은 인자 파서가 그 값을 두 번째 입력 파일로 인식해 accessible.txt를 LlamaParse로 별도 전송하므로 custom_prompt가 실제 적용되지 않는다.

### Step 4: Primary base 생성

**최종 산출 파일명 규칙** (fused에 어느 파서를 통합했는지 파일명으로 드러낸다): 최종 fused 파일은 `<파일명>_fused_v3_<파서조합>.md`로 명명한다. `<파서조합>`은 **실제로 이 결과물에 내용이 반영된 파서만** Primary부터 나열하고 `+`로 잇는다. 파서 토큰은 개별 출력 접미사와 동일하게 쓴다: `llamaparse`·`upstage`·`gemini`·`mistral`·`opendataloader`·`hwpxlocal`·`corepin`·`gvision`. 단순 대조만 하고 텍스트를 병합하지 않은 파서는 넣지 않는다(파일명이 곧 "무엇을 합쳤는가"의 기록이므로). 예: LlamaParse Primary에 Upstage heading·메타데이터를 패치하면 `_fused_v3_llamaparse+upstage.md`, Mistral 단독 채택이면 `_fused_v3_mistral.md`, hwpx_local 단독이면 `_fused_v3_hwpxlocal.md`. **Primary base를 만들 때는 Primary 파서명만 붙이고, Step 6에서 보조 파서 내용을 실제로 반영할 때마다 파일명에 `+<파서>`를 덧붙여 rename한다.**

#### LlamaParse v2 Primary

```bash
cp "<파일명>_llamaparse.md" "<파일명>_fused_v3_llamaparse.md"
```

텍스트 위주 문서(법률·논문·보고서)는 이미지 placeholder만 정리하면 즉시 퓨전 진입 가능. **인쇄용 책자·다이어그램 풍부 문서**(인포그래픽·챕터 표지·헤더 inline 아이콘 등)는 `references/postprocess.md`의 v2 후처리 7가지 패턴 적용.

⚠️ **이미지 placeholder는 단순 제거 금지**: 학술 보고서에서도 본문 정보 다이어그램이 1~2건 섞여 있음. `generate_alt_text.py`로 한국어 풍부 alt를 먼저 생성한 뒤, 표지·로고·디자인 라벨은 제거하고 **본문 정보 다이어그램은 `(이미지: <alt>)` 형태로 inline 보존**.

```bash
python <스킬루트>/scripts/generate_alt_text.py \
    --pdf "<파일>.pdf" --markdown "<파일>_llamaparse.md" \
    --output "<파일>_with_alt.md" --map "_work-docparse/<파일>_alt_map.json"
```

생성된 alt를 검토하여 본문 다이어그램만 fused에 inline 삽입. 표지·로고는 제거.

#### ODL Primary (폴백)

```bash
python <스킬루트>/scripts/normalize_odl.py "<odl_output.md>" "<파일명>_fused_v3_opendataloader.md"
```

자동 처리 항목 상세는 `references/postprocess.md` 참조.

⚠️ **ODL Primary 채택 전 본문 숫자 검증 필수** (텍스트 레이어 있어도): 출판 임베딩 폰트의 글리프 매핑이 깨져 ODL이 본문 숫자/특수문자를 전부 누락하는 경우 존재. 본문 첫 문단 1~2개 숫자를 v2/Upstage와 즉시 대조. 누락 확인 시 ODL Primary 폐기. 상세는 `references/tier-rules.md`.

### Step 5: 데이터 무결성 게이트

Primary 선정 직후, LLM 교차 검증 전에 반드시 실행. **표에 숫자 데이터가 있는 문서에서는 생략 불가.**

1. **산술 검증**: 모든 표의 숫자 행 합계 검증 (`개별항목 합 == 소계` 등). 비용 0.
2. **불일치 발견 시**: 보조 파서에서 해당 표 숫자를 추출하여 셀 단위 대조. 포맷이 지저분해도 숫자 값 자체는 추출 가능("포맷 품질 ≠ 데이터 정확도").
3. **셀 위치 비교 (가장 중요, 생략 불가)**: 산술 검증과 무관하게 **항상** 수행. 합계가 맞아도 카테고리가 뒤바뀔 수 있음. 2파서 일치 시 채택, 불일치 시 3번째 파서로 다수결. **Gemini 표 데이터는 다수결 투표에서 제외** (스캔 양식 열 배정 신뢰도 D).
4. **불일치 해소 불가 시**: 3자 교차 검증용 추가 파서 실행 (Mistral).

⚠️ **산술 검증만으로는 열 이동을 탐지할 수 없다.** Step 5.3 셀 위치 비교가 유일한 방어선. 실측 사례: 합계 7이 동일하지만 `법정한부모=2,그외저소득=1` → `그외저소득=2,다문화=1`로 열 이동 (2026-04).

### Step 6: LLM 교차 검증 및 패치

**6a. heading 갭 패치**

```bash
python <스킬루트>/scripts/compare_outputs.py "<primary.md>" "<upstage.md>"
```

갭 있는 heading 구간만 Upstage에서 읽어 Edit으로 삽입.

**6b. 텍스트·숫자 교차 검증**

현재 fused 파일(`_fused_v3_<파서조합>.md`)의 대표 구간 3~5곳(시작부·중간부·표 밀집 구간·끝부분)을 보조 파서 출력과 비교. 보조 파서가 더 정확하면 교체, 둘 다 다르고 판단 불가하면 Mistral 추가. **LlamaParse v2 메타데이터 생략 경향** (출력자·전자서명자·원본대조필 등 행정 메타데이터)은 Upstage에서 보완. **보조 파서의 텍스트를 실제로 반영(교체·패치)했다면, 파일명의 `<파서조합>`에 그 파서를 `+<파서>`로 추가해 rename한다**(Step 4 명명 규칙).

**6c. 표 데이터 정합성**

표에 숫자 데이터가 있는 문서는 **필수**. Step 5에서 1건이라도 불일치가 나왔으면 Mistral 추가 실행으로 3자 교차.

### Step 7: 최종 노이즈 정리

최종 fused 파일(`_fused_v3_<파서조합>.md`) 최종 점검. OCR 아티팩트(`一`, `□`), 페이지 경계 고아 줄, 중복 heading, 환각 텍스트, 이미지 placeholder 잔재, Upstage OCR 단어 분절, HTML 체크박스 아티팩트, 반복 페이지 푸터 등. 상세 체크리스트는 `references/postprocess.md` Step 7 절.

### Step 8: 출력 및 정리

**원칙**: 최종 결과물(`_fused_v3_<파서조합>.md`)은 작업 폴더에 남기고, 그 전까지의 부산물(개별 파서 출력)은 `_work-docparse/` 하위 폴더로 격리한다. 폴더명은 출처(docparse) + 성격(work=중간 작업물)을 드러내며, hwpx-automation 스킬의 `_work-hwpx-automation/`과 접미사 규칙이 통일된다.

1. `[파일명]_fused_v3_<파서조합>.md`로 작업 폴더에 저장(파서조합 명명 규칙은 Step 4 참조). **저장 직전, 파일명의 파서 목록이 실제로 내용이 반영된 파서와 일치하는지 확인한다**(Primary만 쓰고 보조 파서를 반영했는데 rename을 빠뜨리지 않도록).
2. 대화에 요약 출력: 페이지 수·티어·사용 파서·실패/타임아웃 파서·퓨전 방식·자동화 교정 항목 수·LLM 교차 검증 결과·최종 줄 수·표 개수 + **Step 9의 두 결과**(추가 교차검증 실행/불필요와 근거, 규칙 문서 반영 내역).
3. 개별 파서 출력을 `_work-docparse/` 하위 폴더로 이동:

```bash
mkdir -p "<파일 디렉토리>/_work-docparse"
mv "<파일명>_llamaparse.md" "<파일명>_upstage.md" "<파일 디렉토리>/_work-docparse/"
# 사용된 경우 _gemini.md, _mistral.md, _opendataloader.md, _hwpxlocal.md도 이동
# (HWPX 티어: hwpx_local 단독이면 _hwpxlocal.md를 _fused_v3_hwpxlocal.md로 채택)
```

### Step 9: 사후 절차: 추가 교차검증 검토 + 학습 반영 (생략 불가)

fused 산출로 작업이 끝나지 않는다. 매 파싱 작업의 끝에 아래 두 절차를 수행하고, 그 결과를 Step 8의 요약 출력에 한 줄씩 포함한다(2026-06-12 신설).

**9a. 추가 파서 교차검증 필요성 검토.** 다음 중 하나라도 해당하면 추가 파서(주로 Mistral, 상황에 따라 ODL·Gemini)를 실행해 3자 투표로 종결한다. 해당이 없으면 "추가 교차검증: 불필요"와 근거를 요약에 명시한다.

| 트리거 | 추가 파서 | 근거 |
|--------|----------|------|
| 2자 파서 간 불일치 쟁점이 미해소로 남음 (날짜·고유명사·정답 등) | Mistral (또는 PDF 시각 판독) | 2:1 다수결 + 원본 확인으로 종결. 쟁점을 fused에 "[OCR 불확실]"로 남긴 채 끝내지 않는다 |
| 비한국어·혼합 언어 자료 | Mistral | tier-rules "비한국어 조건 정밀화" 참조: 스캔+라틴계 외국어는 1급, 텍스트 레이어 한국어 혼합은 투표용 |
| 정확성 critical(시험지·법률·의무기록)인데 2종 이하로 파싱함 | 3종째 파서 | tier-rules의 3자 교차 원칙 |
| 보고서 부록에 전례 없는 **새 문서 유형** | 1종 추가 | 파서 성능 데이터 수집 겸 실행(부록 신설 재료) |
| 원본 자체 오타 의심 표기를 발견 | 1종 추가 또는 시각 판독 | 3자 일치 시 "원본 오타 확정"으로 기록 가능 |

**9b. 학습 반영.** 검증으로 재사용 가능한 새 패턴을 발견하면 해당 규칙 문서에 즉시 반영해, 다음 작업이 같은 시행착오를 반복하지 않게 한다:

1. **티어 선택·파서 전략을 바꾸는 발견** → `references/tier-rules.md` 갱신 + SKILL.md 파서 비교표 반영.
2. **후처리·노이즈 정리 패턴** → `references/postprocess.md`.
3. **함정·에러 처리** → `references/gotchas.md`.

발견의 크기에 따라 새 규칙을 추가하거나 기존 항목에 사례를 덧붙인다. 사용자에게 영향이 있는 변경은 `CHANGELOG.md`에 버전 항목으로 기록한다.

## 환경 변수

| 변수 | 필수 여부 | 비고 |
|------|----------|------|
| `LLAMAPARSE_API_KEY` | **medium 이상** (Primary) | LlamaParse v2 agentic. 10크레딧/p, 무료 월 10,000 |
| `UPSTAGE_API_KEY` | medium 이상 (교차검증) | 완전성·메타데이터 보완 |
| `GEMINI_API_KEY` | small 티어 / alt text 생성 | ≤15p Primary 또는 generate_alt_text.py |
| `MISTRAL_API_KEY` | 조건부 (불일치·비한국어 시) | 3자 교차 검증용 |
| `COREPIN_API_KEY` | 조건부 (HWP 네이티브·한국어 문서 비교) | Corepin 통합 문서 파서. 장당 2원, 무료 100p/월 |
| `GOOGLE_VISION_API_KEY` | 조건부 (수기 손글씨 답안) | Vision 파서 인증(API 키). 또는 `GV_TOKEN`(=`gcloud auth print-access-token`)+`GV_PROJECT`. Vision API 활성화 필요. 무료 1,000p/월 |
| Java Runtime | large 이상 (ODL 폴백) | OpenDataLoader용 |

## 자주 참조하는 부록

- **주의사항·에러 처리·동기화**: `references/gotchas.md`
- **손글씨 충실 전사 (최고 방법·모델 비교·캐스케이드 프롬프트)**: `references/handwriting-cascade.md`
- **변경 이력**: `CHANGELOG.md` (저장소 루트)
