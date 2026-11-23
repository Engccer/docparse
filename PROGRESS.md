# 진행 상태

## 현재 상태

- 버전은 `SKILL.md`의 `metadata.version`이 정본이다. 파서는 `parsers/*_parse.py` 15종(로컬 5, 클라우드 10)이다.
- Cohere·OpenAI·Anthropic·Azure 파서는 등급과 티어 배정이 없는 후보다(OpenAI만 ODT에서 1순위로 쓴다). Anthropic·Azure는 합성 스캔 3쪽 1건으로만 실호출을 확인했다.
- ODT는 `content.xml` 전수 대조 게이트(`scripts/odt_verify.py`)를 통과한 출력만 쓴다.
- HWPX는 밑줄 빈칸이 발견되면 밑줄 보존을 자동으로 켠다(hwpx-tomd 0.5.0 이상).
- 남은 일은 `docs/BACKLOG.md`에 있다.

## CLI 오류·도움말 계약

- 모든 파서는 `--help`를 API 키·SDK 로딩보다 먼저 처리한다. LlamaParse·Mistral OCR은 인자·파일 검사도 SDK 로딩보다 먼저 한다.
- 실제 서비스 응답 품질과 문서별 누락·오인식은 이 계약의 범위 밖이며 실제 문서 작업에서 확인한다.

## 이미지 수치표 다중 판독 대조

- 표가 그림으로 박힌 문서의 수치표를 `image_tables.py`(격자 세기·조각) → 판독 4벌 이상 → `md_to_reading.py` → `cell_vote.py`(칸별 대조) → 갈린 칸 재확인 순서로 처리한다. 절차의 정본은 `references/image-tables.md`.
- 진단(`assess_document.py`)이 이미지 덮임과 유효 DPI를 잰다. Tier 0(pdfplumber)은 복원 가능한 병합 칸을 HTML 표로 낸다.
- 근거는 1문서다(63쪽 카탈로그). 판독 조합의 우열은 다른 문서에서 다시 재야 한다.
