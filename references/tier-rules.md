# 티어 결정 후 적용하는 보정 규칙

SKILL.md Step 2의 기본 티어 표만으로는 부족한 문서 유형별 예외 규칙. 사전 진단(`assess_document.py`) JSON과 문서 특성을 보고 아래 규칙을 적용한다.

## 텍스트 레이어 없음 (스캔/이미지 PDF)

ODL은 텍스트 레이어 필수이므로 **스캔 문서에서는 사용 불가**. 티어별 대체:

- **small (≤15p)**: Gemini 단독 (OCR 내장). **단, 표에 숫자 데이터가 있는 스캔 양식은 "스캔+표 숫자" 규칙(아래)을 따른다(Gemini 단독 불가)**. ⚠️ Gemini는 thinking 모델(`gemini-3.5-flash`)이라 장문에서 요약화하므로 small에서도 ≤15p를 넘기지 말 것. `gemini_parse.py` 기본값(`thinking_budget=0`)이 요약화를 막는다(2026-06-28, 부록 M).
- **medium (16~60p)**: LlamaParse v2 Primary + Upstage 교차검증 (표 열 정확도·OCR v2 최상, 80p 스캔 의무기록 A등급 검증).
- **large (61~100p)**: LlamaParse v2 Primary + Upstage + Mistral 권장.
- **xlarge (101p+)**: LlamaParse v2 Primary + Upstage + Mistral (크레딧 부족 시 Upstage Primary로 폴백).
- 모든 티어에서 OCR 파서 필수. `assess_document.py`가 한 단계 위 티어를 자동 반환할 수 있다.
- **정확성 critical 문서** (의무기록, 법률문서, 계약서): 티어 무관 최소 3자 교차검증.

## Mistral Primary 고려 조건

기본은 Upstage Primary지만, 아래 조건 충족 시 Mistral Primary 전환 가능:

- **영어 비율 50% 이상**: 의학기록, 기술문서, 코드 포함 문서.
- **정형화된 양식 문서**: 체크박스·표·고정 필드 위주. 자유 서술형 한국어가 적음.
- **단, 한국어 자유 서술 위주 문서**(보고서·논문·정책)에서는 Mistral 환각 위험 여전 → Upstage Primary 유지.
- Mistral Primary 시에도 Upstage 병행하여 heading 구조 보강.

### Mistral ocr-4 헤딩 생성 (2026-06-28, 부록 M)

`mistral-ocr-latest`가 `mistral-ocr-4`를 가리키며(이전 `ocr-2512`), **헤딩 구조 생성이 추가**됐다(187p 텍스트PDF에서 헤딩 5→76, 17개 섹션·하위절 정확). 텍스트PDF에서 **187페이지를 17개 섹션까지 완전 전사한 유일한 출력**이라, LlamaParse v2 크레딧 부족 시 **ODL과 함께 폴백 Primary 후보로 격상**한다. 전제: ① `- N -` 노이즈 185건 정규식 strip, ② OCR 글자 드리프트(`장애전형→장애인형`, `부분→부문`) 패치(텍스트 레이어 추출 또는 Gemini 교정어 대조). 헤딩 레벨이 거칠게 들쭉날쭉한 점도 후처리 대상.

## Mistral 추가 조건 (Upstage Primary일 때 교차검증 목적)

- ODL↔Upstage 간 표 데이터 불일치 발견 (3자 교차).
- 텍스트 판단 불가 구간이 다수.
- 비한국어 문서 (`--lang` ≠ `ko`): 단, 아래 2026-06-12 정밀화 참조.
- 스캔 문서 large/xlarge에서 Gemini 커버리지 부족 (30p+ 누락).

### "비한국어 문서" 조건 정밀화 (2026-06-12 프랑스어 교과 자료 12건 실측)

- **Mistral은 순수 비전 OCR로, 텍스트 레이어를 활용하지 않는다.** 텍스트 레이어가 있는 PDF에서도 OCR 경로로 처리해 작은 글씨 한국어가 대량 훼손되고(의미 반전 오독 포함), **일러스트·워터마크에 가려진 숨김 텍스트 레이어는 원천 추출 불가**(교과서 듣기 지문 미회수 실증). 숨김 텍스트가 의심되는 문서에서 Mistral 단독 금지, 텍스트 레이어 추출(PyMuPDF)·ODL 병행.
- **(승격) 스캔 + 라틴계 외국어**: 1급 교차검증 파서이자 Primary 후보(A-). 스캔 프랑스어에서 악상 충실도 3파서 중 최고, LlamaParse 단락·문항 번호 누락 회수 실적. 스캔이면 v2 + Mistral + Upstage 3종을 기본으로.
- **(강등) 텍스트 레이어 있는 한국어 혼합 문서**: 패치 소스로 부적합(C- 안팎). 쟁점의 3자 투표용으로만 사용.
- **무단 정규화 경계**: 원본 인쇄 오타를 표준형으로 고쳐 쓰는 습성(관측된 수기 교정 사례와 동일 계열). 원본 오타 보존 판정은 Mistral로 하지 않는다.
- **이미지 영역 양극화**: 누락 아니면 그럴듯한 날조(가짜 표 행 대량 생성 사례). 이미지 내 텍스트 회수는 LlamaParse·Upstage·시각 판독으로.

## 크레딧 부족 시 폴백

LlamaParse v2 잔여 부족 시 ODL Primary + Upstage 교차검증(v2 이전 전략)으로 폴백. 사전 확인:

```bash
python "<스킬루트>/parsers/llamaparse_parse.py" --credits
```

## ⚠️ ODL Primary 채택 전 본문 숫자 검증 (텍스트 레이어 있어도 필수)

`assess_document.py`가 `has_text_layer: true`로 보고하더라도 출판 임베딩 폰트(특히 학술 보고서·연구 보고서)는 글리프 매핑이 깨져 **ODL이 본문 숫자/특수문자를 전부 누락**할 수 있다. ODL Primary 채택 시:

1. ODL 출력의 본문 첫 문단(서론·요약 등) 1~2개 숫자(연도·통계 등)를 v2/Upstage와 즉시 대조.
2. 누락 확인되면 ODL은 Primary에서 제외, v2 또는 Upstage로 전환.
3. 누락 패턴: `2023년 4월 ... 508,850명 중 4,579명으로 0.90%` → `년 월 ... 명 중 명으로 차지`.

실측: 한 학술 보고서(554p, 텍스트 레이어 있음)에서 ODL 본문 숫자 전체 누락(2026-05-14). v2와 Upstage는 정상.

## 학술/연구 보고서 (정형 텍스트 + 표 풍부)

인쇄용 책자(인포그래픽 풍부)와 달리, 학술 보고서는 v2가 시각 디자인 크기에 끌려 **같은 깊이의 절에 무작위로 H1/H2/H3 부여**하는 경향. 예시: `## 1. 연구의 필요성 및 목적` 뒤에 `# 2. 연구 내용 및 범위`, `# 3. 연구 운영 체계`.

- ODL normalize 후 헤딩 위계가 v2보다 훨씬 안정적인 경우 다수.
- 단, **ODL Primary 채택 전 위 본문 숫자 검증 필수** (이 케이스에서 ODL 채택 불가가 빈번).
- 폰트 문제로 ODL 채택 불가 시: v2 Primary 유지 + 챕터 H1만 수동 정리(본문 절 위계 정규화는 가성비 낮음).

## 스캔 문서 + 표에 숫자 데이터 (신청서·양식·집계표)

**페이지 수·티어 무관, 최고 난이도로 분류**. 스캔 이미지의 병합 셀 표는 모든 파서가 셀 위치를 틀릴 수 있어 단일 파서 신뢰 불가.

- ODL은 스캔 미지원이므로 제외.
- **최소 3개 파서 필수**: **Upstage Primary** + Mistral 교차검증 + LlamaParse v2(텍스트·체크리스트 보조).
- **⚠️ Gemini·LlamaParse v2 모두 스캔 수기 양식 병합 셀에서 열 이동 발생**:
  - Gemini: 개별·합본 모두 불안정.
  - LlamaParse v2: 개별 PDF에서도 개별 신청서 케이스에서 1건 오류(2026-04 실측).
  - **수기 양식 표 숫자의 Primary·교차검증에서는 Upstage + Mistral만 사용**.
- Primary 선정 후 반드시 데이터 무결성 게이트(Step 5) 적용.
- 산술 검증 + 셀 단위 교차 대조 필수.

## 스캔 문서 + 인쇄체 표 (의무기록 검사결과 등)

LlamaParse v2 Primary 가능. 80p 스캔 의무기록에서 표 열 정확도 A+, OCR A 검증됨 (COL2A1 정확, Urine 정확, Upstage의 단어 분절 문제 없음). Upstage 교차검증 병행 권장.

## 동일 양식 다수 합본 PDF (스캔 신청서 N건 합본)

- **합본 시 열 이동 오류가 증폭됨**: 개별 PDF에서 3파서 모두 정확했던 문서가 합본 시 Gemini에서 열 이동 발생 (2026-04 실측: 개별 신청서).
- **권장**: 가능하면 **개별 PDF를 각각 파싱**한 뒤 결과를 결합. 합본 일괄 파싱보다 정확도 현저히 높음.
- 개별 파싱 불가 시: Upstage Primary 필수, **Gemini는 합본 표 데이터에 사용 금지**, Step 5.3 셀 위치 비교 강제 적용.

## 손글씨 위주 스캔 문서 (충실 전사 critical)

**손글씨(수기)가 본문 대부분이고, 철자·표기를 원형 그대로 보존해야 하는 스캔 문서** 전반. 학생 서술형 답안(채점), 수기 설문 자유응답, 신청서·양식의 자필란, 편지·필사본·현장 기록(field notes), 수기 의무기록 메모 등. 공통 제약: **오기·비표준 표기 자체가 정보**(채점 요소·법적 원본성·신원 단서)이므로 **파서의 무단 교정·환각이 곧 무결성 훼손**이다. (실측 토대: 2026-06-11 영어 쓰기 수행평가 22p / 2026-06-14 Tesseract·Google Vision 실측, changelog v3.10·v3.13)

> **적용 범위 판단**: "있는 그대로의 글자"가 중요할 때만 이 규칙을 적용한다. 손글씨라도 *요지만* 필요하면(회의 메모 요약 등) LLM 파서의 매끄러운 출력이 오히려 편하다. 충실성이 critical할 때만 아래 파이프라인.

### 핵심 원리: LLM 파서의 2종 실패와 방어

1. **무단 자동교정(silent correction)**: 오기를 사전형으로 고침. Mistral `studise→studies`·`mistaks→mistakes`·`shoud→should`, LlamaParse `shoud→should`.
2. **단어 환각(hallucination)**: 없는 단어·인명 생성. LlamaParse `Dear me→Mr. Han`, `the end→In the end`.

둘 다 **유창한 문장 속에 숨어** 산술·구조 검증으로 못 잡고 시각 대조만이 방어선이며, LLM 파서는 **단어별 confidence가 없어** 어디를 볼지 신호도 못 준다. → **비-LLM OCR(특히 Google Vision)이 (a) 오기 literal 보존 + (b) calibrated confidence로 검증 표적 제공**으로 정확히 보완한다.

### 권장 4단계 파이프라인

```
① LlamaParse v2 (llamaparse_parse.py)  → 구조·레이아웃·체크박스·reading order
② Google Vision (gvision_parse.py)   → literal 충실 추출 + 단어별 conf (저신뢰 ~7% 자동 표시)
③ ①↔② diff + ② 저신뢰 단어          → 환각/교정/오독 후보 = 육안 표적 (전수 → 표적)
④ 시각 판독 + (있으면) 명부/원장 대조 → ③ 표적만 집중. 신원 필드는 ②의 저신뢰 flag가 대조 대상 지정
```

③은 `python scripts/diff_fidelity.py <llm.md> <gvision.md> --out targets.md`로 자동화한다(토큰 정렬로 발산 토큰 + OCR 저신뢰를 페이지별 표적으로 출력. 한글 띄어쓰기·구두점·태그·conf 주석 노이즈는 자동 필터). 실측: 한 학급 22장에서 `Mr. Han`(환각)·`한글 손글씨 이름`(이름 오독, conf 0.16)을 발산+저신뢰로 이중 포착.

근거(한 학급 22장 실측):
- **충실성**: Tesseract·Vision 모두 위 2종 실패를 구조적으로 안 범함. Vision은 garbling 없이 정확.
- **타깃팅(calibration)**: **Tesseract conf는 무용**(평균 0.35~0.59, 저신뢰 50~92% 과다). **Google Vision conf는 잘 calibrated**(평균 0.91~0.99, 저신뢰<0.90 중앙 ~7%)되고, 저신뢰가 실제 쟁점(지운 글자·취소선·오독한 이름 conf 0.16·체크박스)에 정확히 안착. 명확한 오기(studise·raival)는 고신뢰 보존 → 검증 낭비 0.

### ★ 최고 충실 = Vision→Claude 비전 캐스케이드 (2026-06-17, 5-subset 실측)

위 4단계가 LlamaParse v2 구조 + diff 표적팅 경로라면, **단일 방법으로 가장 충실한 것은 Vision→Claude 비전 캐스케이드**다(영어 쓰기 수행평가 4개 학급 합본 약 80명 실측, 5/5 최고). 상세 워크플로우·repair 프롬프트·모델 비교·속도는 **`references/handwriting-cascade.md`**.

- **방법**: ① `gvision_parse.py --raw`(리터럴 철자 + 단어별 confidence) → ② 각 페이지 **이미지 + Vision 드래프트**를 Claude 비전(Sonnet 권장·저비용, Opus 동급)에 주고 *"Vision 철자를 기본 권위로, 이미지가 명백히 다른 글자일 때만 교정"* 프롬프트로 repair. Vision의 리터럴 충실 + Claude의 순서·가독성을 결합.
- **모델 비교(충실도)**: **Claude Opus 4.8 ≈ Sonnet 4.6** > Google Vision 단독(리터럴 최강이나 읽기순서 붕괴로 단독 불가) > **Gemma 4 12B·Haiku 4.5 = 탈락**(윤문+환각, 런마다 불안정: Roblox→Wumpus, 인사말→favorite saying). 단독 비전도 가장 어려운 오기를 가끔 윤문(speacial→special, guiter→guitar, didn4→didn't)하나 캐스케이드가 보완.
- **모드 선택**: 충실 critical(채점·저숙련 답안 합본) = **캐스케이드** / 속도 critical 대량 = **Claude 단독 비전**(1콜, Vision 불필요). 속도 실측(~22~23p): Vision OCR ~35s, 단독 ~85~140s, 캐스케이드 ~190~250s(표준 단독의 1.4~2배).
- **잔여 약점**: `didn4`류 디짓-인-워드 오기는 Vision이 4를 t로 오독→캐스케이드가 추종 가능(단독 Opus가 오히려 잡기도). repair 프롬프트의 디짓 예외 규칙 + 시각 판독으로 보강.

### 파서·도구별 주의 (일반)

- **Mistral** (ocr-4): 수기 오기 대량 무단 교정(`studise→studies`) 여전 + 수기 한글 이름 13/22(개선했으나 무관 이름 날조 잔존, PII 위험) → 수기 **본문 정본·교차 부적합 유지**.
- **Gemini** (3.5-flash, thinking): 구버전의 "체크박스 페이지 단위 뒤집음(F)"과 "흘림체 본문 붕괴"가 **thinking ON에서 해소**됨: 체크박스 F→A(자필 틱마크까지 정확), 난필 환각 붕괴 해소, 한글 이름 22/22. → **체크박스·한글이름 보조 패치원으로 격상**(`gemini_parse.py --thinking`으로 호출). ⚠️ 단 (a) 일부 페이지 학생 철자를 표준형으로 무단 교정하는 신규 회귀가 있어 **본문 verbatim 정본은 여전히 부적합**, (b) `thinking_budget=0`(파서 기본)이면 자필 체크박스 판독이 다시 무너지므로 체크박스 패치는 반드시 `--thinking`으로. 본문 verbatim 정본은 GV+Opus 캐스케이드 유지.
- **Upstage**: 글자 단위 충실도는 높으나(오기 보존) 단어·줄 파편화 심함 → 사람이 재조립 필요.
- **Google Vision 약점(병행 필요)**: ⓐ 복잡 레이아웃에서 reading order 흐트러짐 → ① 병행. ⓑ 체크박스 V표 유무 판정 불안정 → ① + 시각 유지. ⓒ 한글 손글씨 오독 가능(단 저신뢰 flag → 대조 자동 타깃). ⓓ 클라우드 전송 → **민감정보(학생·환자 등) PII 정책 확인 후 사용**(무료 1,000p/월).
- **완전 로컬·PII 절대조건**: ②를 Tesseract로 대체 가능하나 calibration 포기 → ③ diff 신호 의존(무료·유효). 더 정확한 로컬 대안 TrOCR/EasyOCR(설치 부담). **엔진 선택 상세·벤치마크·언어 지원은 `references/handwriting-ocr-engines.md`**.
- **인증·실행**: `export GV_TOKEN="$(gcloud auth print-access-token)" && export GV_PROJECT="<projectId>"` 후 `python parsers/gvision_parse.py <파일> < /dev/null`. Vision API 활성화(`gcloud services enable vision.googleapis.com`).

### 신원 필드(이름·ID 등) 교차 확인

수기 신원 필드는 모든 파서 신뢰 불가(최고 20/22). ① 본문 내 단서(영문 서명 등)와 교차 ② 명부·원장 정렬 순서(가나다순 등) 정합성 ③ 고해상(300dpi+) 확대 판독의 3중 검증. **Vision의 저신뢰 flag가 "어느 필드를 확인할지" 자동 지정**(예: 3글자 한글 손글씨 이름 오독을 conf 0.16으로 표시). 명부 파일(xlsx 등)이 있으면 Step 5에 대조 추가.

### 시각 판독 실행법 (공통)

PyMuPDF로 헤더·쟁점 구간을 크롭(폭 1500px 이하)해 서브에이전트 3~4기에 분담 판독 위임(메인 컨텍스트 이미지 한도 회피, gotchas.md 참조). 모호 글자는 8~14배 확대 후속 질의로 확정.

### fused 출력 (충실 전사 규칙)

오기를 그대로 보존(diplomatic transcription)하고, 취소선·행간 삽입·여백 낙서도 기록. 모호 글자의 채택 근거는 "판독 노트" 부록으로 남긴다.

### 대표 사례: 학생 서술형 답안 합본 (채점 보조)

1인 1페이지 합본 + 자기점검 체크박스. 철자·문법 오류가 채점 요소. 체크박스는 LlamaParse v2 최우수(22p 중 20p 일치), **Gemini 금지**(페이지 단위로 전체 체크/미체크 뒤집음). 이름·학번은 위 "신원 필드" 절 + 채점표(xlsx) 명단 대조. 상세 워크플로우는 작업 폴더의 메모.

## 시험지·고사 원안·평가지 (객관식 옵션 포함)

**페이지 수·티어 무관, 최소 3종 파서 교차검증 필수**. 옵션 텍스트 한 글자가 정답을 좌우하므로 small 티어(≤15p)에서도 Gemini 단독 신뢰 불가.

- **권장 조합**: Gemini + Upstage + ODL 3종 (텍스트 레이어 PDF). ODL은 텍스트 레이어 직접 추출로 옵션 텍스트·순서·원숫자(ⓐⓑ⋯) 마킹이 가장 정확.
- **Gemini 약점** (2026-04 실측, 5p 영어 시험지): 옵션 순서 깨짐(① ④ ② ⑤ ③), `①~⑤` → `1.~5.` 강제 변환, ⓐ → ⓠ OCR 오인식.
- **Upstage 약점**: I → | OCR 노이즈(영어 대문자 I), ⓒ → Ⓒ 변환, HTML 표 마크업 잔존.
- **ODL 약점**: 마크다운 형식이 표/`<br>` 혼재로 가독성 낮음 → LLM 후처리 필수.
- **정답표 동봉 시**: 정답 인덱스(①~⑤)와 본문 옵션 매칭 검증을 Step 5에 추가 (배점 합계, 문항 수도 함께 검증).

## PDF Read 도구의 시각 렌더링 = ground truth (≤20p)

Claude Code의 `Read` 도구는 ≤20p PDF를 시각 이미지로 렌더링해 직접 읽음. 파서 출력 cross-validation의 **최종 결정자(authoritative source)**로 사용 가능.

- 시험지·법률문서·의학문서 등 정확성 critical 소형 PDF에서 특히 유용.
- 파서 3종이 서로 다른 결과를 낼 때 PDF Read로 직접 확인하면 즉시 결정 가능.

## 비PDF 문서 포맷별 파서 선택

| 포맷 | 파서 | 비고 |
|------|------|------|
| HWPX | `hwpx_local_parse.py` (1순위) | 무료, 로컬, hwpx-tomd 엔진. 표 구조 정확·자가검증 내장. 이미지 내 텍스트·레이아웃·경고 시 Upstage 교차/대안 |
| HWP | HWPX 변환 후 `hwpx_local_parse.py` | `hwpx-automation/convert/hwp2hwpx.bat`로 변환 → HWPX와 동일 처리 |
| DOCX/PPTX | Upstage + LlamaParse v2 | Mistral 선택 추가 가능 |
| XLSX | Upstage + LlamaParse v2 | 표 구조 비교 |
| JPG/PNG | Upstage + Gemini | OCR + 텍스트 품질 |

### HWP/HWPX 파싱 세부 절차

1. HWP → `hwpx-automation/convert/hwp2hwpx.bat <입력.hwp>`로 HWPX 변환 (Java, 서식 보존).
2. HWPX → `parsers/hwpx_local_parse.py <파일.hwpx>`로 마크다운 변환(출력 `_hwpxlocal.md`). 긴 지문이 셀 안에 있으면 `--cell-br`.
3. 이미지 경고·recall/마커 경고가 뜨거나 시각적 배치 재현이 중요하면 Upstage 추가 실행하여 비교.
4. kordoc(`npx kordoc`)는 HWP 바이너리 파싱 가능하나 표 중심 HWPX 문서에서 파싱 실패 사례 확인됨(2026-03). 교차검증 도구로 비권장.
5. HWPX 편집(`--set-cell`/`--find` 등)은 docparse가 아니라 `hwpx-automation` 스킬의 `hwpx_edit.py`를 쓴다(docparse는 읽기 전용).

### 포맷별 호환성 매트릭스

| 포맷 | hwpx_local | Upstage | Gemini | LlamaParse v2 | Mistral | OpenDataLoader |
|------|-----------|---------|--------|--------------|---------|----------------|
| PDF | - | O | O | O | O | O |
| JPG/PNG | - | O | O | O | O | - |
| HWPX | **O (1순위)** | O | - | - | - | - |
| HWP | O (변환 후) | O | - | - | - | - |
| DOCX | - | O | - | O | O | - |
| PPTX | - | O | - | O | O | - |
| XLSX | - | O | - | O | - | - |
