# 변경 이력

이 프로젝트의 주요 변경 사항을 버전별로 정리합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/)를 따릅니다.

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
