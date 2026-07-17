# docparse

> English summary: an adaptive document parsing toolkit. It pre-diagnoses a document, picks the best parser combination for that document's tier, runs them, and fuses the results (Primary + Patch) into a single high-quality Markdown file. Works as a standalone CLI and as a Claude Code skill (`/docparse`).

**docparse**는 적응형 문서 파싱 도구입니다. 문서를 먼저 사전 진단해 그 문서의 티어에 맞는 최적의 파서 조합을 고르고, 실행한 뒤, 결과를 Primary + Patch 방식으로 퓨전하여 하나의 고품질 마크다운으로 만듭니다. 개별 파서를 직접 실행하는 독립 CLI로도, Claude Code 스킬(`/docparse`)로도 동작합니다.

## 주요 특징

- **적응형 티어 선택**: 사전 점검(페이지 수, 텍스트 레이어, 포맷)으로 각 문서를 티어(hwpx / small / medium / large / xlarge)로 분류하고 파서 전략을 자동으로 정합니다.
- **Primary + Patch 퓨전**: 한 파서를 Primary 베이스로 삼고, 나머지 파서는 전체를 다시 파싱하는 대신 빠진 부분(누락된 헤딩, 표 셀, 메타데이터)만 패치합니다. 작업을 효율적으로 유지하면서 각 파서의 강점만 끌어옵니다.
- **다파서 교차검증**: 숫자 표, 헤딩, 날짜, 고유명사를 파서 간에 대조하고, 데이터 무결성 게이트(산술 검증 + 셀 위치 비교)와 불일치 시 다수결로 판정합니다.
- **무료 로컬 파서 + 유료 클라우드 파서 혼용**: 로컬 엔진(HWPX, OpenDataLoader)은 비용 없이 오프라인으로 동작하고, 클라우드 엔진(LlamaParse v2, Upstage, Gemini, Mistral, Corepin, Google Vision)은 OCR·레이아웃·고완전성 커버리지를 더합니다. 실제로 호출한 클라우드 파서에 대해서만 비용이 발생합니다.

## 파서 라인업

| 파서 | 스크립트 | 출력 | 필요 키 | 역할 |
|--------|--------|--------|--------------|------|
| **hwpx_local** | `parsers/hwpx_local_parse.py` | `_hwpxlocal.md` | 없음 (로컬, 무료) | HWPX 전용, 오프라인. 글상자·`<hp:t>` tail·병합 표 셀을 보존하고 자가검증 3종 수행. `hwpx-tomd` 패키지 필요. 이미지 내 텍스트는 범위 밖. |
| **upstage** | `parsers/upstage_parse.py` | `_upstage.md` | `UPSTAGE_API_KEY` | 베이스라인. 노이즈 필터링·완전성 최강, 메타데이터 우수. |
| **gemini** | `parsers/gemini_parse.py` | `_gemini.md` | `GEMINI_API_KEY` | 텍스트 품질·헤딩 최상. 짧은 PDF(30페이지 이하)에서 신뢰. |
| **llamaparse (LlamaParse v2)** | `parsers/llamaparse_parse.py` | `_llamaparse.md` | `LLAMAPARSE_API_KEY` | medium 이상 PDF의 기본 Primary(agentic 티어). 표 열 정확도·OCR 강함. |
| **mistral** | `parsers/mistral_parse.py` | `_mistral.md` | `MISTRAL_API_KEY` | 대형 문서 완전성·3-way 교차검증. |
| **opendataloader** | `parsers/opendataloader_parse.py` | `_opendataloader.md` | 없음 (로컬, 무료) | PDF 전용. Java 런타임과 기존 텍스트 레이어 필요. |
| **corepin** | `parsers/corepin_parse.py` | `_corepin.md` | `COREPIN_API_KEY` | 다포맷 단일 API 라우터(텍스트 PDF, HWP/HWPX, Office, 스캔 OCR), 한국어 필터링 SLM 내장. 보조·비교용. |
| **gvision** | `parsers/gvision_parse.py` | `_gvision.md` | `GOOGLE_VISION_API_KEY` 또는 `GV_TOKEN` + `GV_PROJECT` | 단어별 confidence를 주는 비-LLM OCR. 오기를 보존해야 하는 손글씨·충실 전사용(자동 교정·인명 환각 없음). |

티어별 Primary 매핑(사전 점검 단계에서 자동 배정):

| 티어 | 조건 | 전략 | Primary |
|------|-----------|----------|---------|
| **hwpx** | HWPX 파일 | hwpx_local 우선, 이미지/레이아웃 중요 시 Upstage 교차검증 | hwpx_local |
| **small** | PDF 15페이지 이하 | Gemini 단독 | Gemini |
| **medium** | PDF 16~60페이지 | LlamaParse v2 + Upstage | LlamaParse v2 |
| **large** | PDF 61~100페이지 | LlamaParse v2 + OpenDataLoader | LlamaParse v2 |
| **xlarge** | PDF 101페이지 이상 | LlamaParse v2 + OpenDataLoader | LlamaParse v2 |

## 설치

```bash
pip install -r requirements.txt
```

참고:

- **Java 런타임**은 OpenDataLoader 파서(large / xlarge 폴백)에만 필요합니다. 그 외에는 선택 사항입니다.
- 로컬 HWPX 파서는 `hwpx-tomd` 패키지에 의존합니다(`requirements.txt`로 설치). 이 패키지가 없는 기기에서는 hwpx_local이 설치 안내를 출력하며, Upstage로 폴백할 수 있습니다.
- 구형 바이너리 **HWP** 파일은 HWPX로 변환한 뒤 투입합니다. 변환 도구는 별도 공개 저장소 [hwpx-automation](https://github.com/Engccer/hwpx-automation)의 `convert/`(JDK 21 기반 hwp2hwpx)를 사용합니다.
- 모든 파서는 독립적입니다. 의존성이나 API 키가 없으면 그 파서 하나만 설치/설정 안내를 출력하고 나머지는 계속 동작합니다.
- 클론 후 `python scripts/check_env.py`를 실행하면 어떤 파서가 바로 사용 가능한지, 무엇을 더 설치하거나 설정해야 하는지(키 발급 URL 포함) 한눈에 확인할 수 있습니다. 읽기 전용이라 아무것도 변경하지 않습니다.

## API 키 설정

샘플 env 파일을 복사한 뒤, 사용할 파서의 키만 채웁니다:

```bash
cp .env.example .env
```

그다음 값을 설정하거나 셸에 export 합니다. 변수는 다음과 같습니다:

| 변수 | 사용 파서 | 필요 시점 |
|----------|---------|---------------|
| `LLAMAPARSE_API_KEY` | llamaparse (LlamaParse v2) | medium 티어 이상 (Primary) |
| `UPSTAGE_API_KEY` | upstage | medium 이상 (교차검증) |
| `GEMINI_API_KEY` | gemini, 대체텍스트 생성 | small 티어 또는 대체텍스트 생성 |
| `MISTRAL_API_KEY` | mistral | 불일치 시 / 비한국어 자료 |
| `COREPIN_API_KEY` | corepin | HWP 네이티브 / 한국어 비교 |
| `GOOGLE_VISION_API_KEY` | gvision | 손글씨 OCR (또는 `GV_TOKEN` + `GV_PROJECT` 사용) |
| `GV_TOKEN` + `GV_PROJECT` | gvision | Vision 대체 인증(OAuth 토큰 + 프로젝트 id) |

각 제공자의 공식 키 발급 URL은 `.env.example`을 참고하세요. 소스에 키를 하드코딩하지 말고 환경 변수만 사용합니다.

## 사용법

### Claude Code 스킬로

```
/docparse                       # 현재 디렉터리에서 지원 파일 자동 탐지
/docparse input.pdf             # 특정 파일 파싱
/docparse input.pdf --lang en   # 비한국어 문서
```

스킬은 전체 적응형 워크플로를 실행합니다: 진단, 파서 선택, 실행, Primary + Patch 퓨전, 교차검증, `<name>_fused_v3_<파서조합>.md` 작성. 파일명의 `<파서조합>`은 실제로 통합에 반영된 파서를 Primary부터 `+`로 나열합니다(예: `_fused_v3_llamaparse+upstage.md`, 단독이면 `_fused_v3_mistral.md`). 이때 중간 파서 출력은 `_work-docparse/` 폴더로 이동합니다.

### 개별 파서 직접 실행

각 파서는 독립 스크립트입니다. 해당 API 키를 먼저 설정한 뒤 실행합니다:

```bash
python parsers/upstage_parse.py input.pdf
python parsers/llamaparse_parse.py input.pdf
python parsers/gemini_parse.py input.pdf
python parsers/hwpx_local_parse.py input.hwpx     # 로컬, 무료, 키 불필요
python parsers/opendataloader_parse.py input.pdf  # 로컬, 무료, Java 필요
```

경로 없이 실행하면 현재 디렉터리에서 지원 파일을 자동 탐지합니다. 출력은 입력 옆에 `<name>_<service>.md` 형식으로 기록됩니다(예: `input_upstage.md`). 보조 스크립트는 `scripts/` 아래에 있습니다(`assess_document.py`, `compare_outputs.py`, `normalize_odl.py` 등).

## 이식성 (코딩 에이전트 호환)

docparse는 Claude Code 스킬로 개발됐지만, 구성요소에 따라 다른 코딩 에이전트(Codex, Gemini CLI 등)에서도 쓸 수 있습니다.

- **완전 이식**: 모든 파서 스크립트(`parsers/*_parse.py`)와 보조 스크립트(`scripts/*`)는 표준 Python CLI입니다. API 키만 있으면 어떤 에이전트에서도, 또는 셸에서 직접 동작합니다. 진단·비교·채점 등 결정론적 처리도 모델과 무관합니다.
- **실행 에이전트에 종속**: 손글씨 캐스케이드의 repair 단계, PDF 시각 판독(ground truth), 퓨전 판단은 스킬을 실행하는 에이전트 *자신의 비전·추론*으로 수행됩니다. 비-Claude 에이전트에서는 그 에이전트의 비전 모델이 이 역할을 맡으므로, 동작은 하지만 품질이 모델에 좌우됩니다(손글씨 충실도 약 98%는 Claude Opus 기준 수치입니다).
- `SKILL.md` 워크플로우 자체는 Claude Code 관용(서브에이전트 위임, 시각 렌더링 등)을 전제로 작성돼 있습니다. 다른 에이전트에서는 개별 파서를 직접 호출하는 방식이 가장 이식성이 높습니다.

## 무료 파서 vs 유료 파서

**무료, 로컬 (API 키 불필요, 오프라인 동작):**

- `hwpx_local` (`hwpx_local_parse.py`): HWPX 전용, `hwpx-tomd` 패키지 필요.
- `opendataloader` (`opendataloader_parse.py`): 텍스트 레이어가 있는 PDF 전용, Java 런타임 필요.

**유료 / 클라우드 (API 키 필요):** `upstage`, `gemini`, `llamaparse` (LlamaParse v2), `mistral`, `corepin`, `gvision`. 여러 제공자가 월 무료 할당량을 주며, 가볍거나 가끔 쓰는 용도에는 충분합니다:

| 파서 | 무료 할당량 (제공자 정책에 따라 변동) | 비고 |
|--------|---------------------------------------------|-------|
| LlamaParse v2 | 월 약 10,000 크레딧 (페이지당 10크레딧) | 현재 한도는 제공자 대시보드에서 확인. |
| Corepin | 월 약 100페이지 | 초과분은 페이지당 과금. |
| Google Vision | 월 약 1,000페이지 | 손글씨/충실 전사용 비-LLM OCR. |
| Upstage, Gemini, Mistral | 제공자별 체험판 / 무료 티어 | 현재 조건은 제공자 가격 페이지에서 확인. |

할당량은 시간이 지나면 바뀝니다. 의존하기 전에 항상 제공자의 현재 가격 정책을 확인하세요.

## 라이선스

MIT. `LICENSE` 참고.

## 관련 프로젝트

시각장애 사용자를 위한 에이전트 스킬 번들 [skills-for-the-blind](https://github.com/Engccer/skills-for-the-blind)의 멤버 스킬이다.
