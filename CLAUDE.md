# CLAUDE.md

이 저장소에서 작업하는 코딩 에이전트가 따르는 항구 규칙이다. 스킬의 동작 규칙은 `SKILL.md`와 `references/*.md`가 정본이고, 이 파일에는 저장소를 고칠 때 모르면 틀리는 것만 둔다.

## 문서 역할

- `SKILL.md`·`references/`: 스킬 사용자(에이전트)가 문서를 파싱할 때 따르는 절차와 판정 규칙. 동작이 바뀌면 `SKILL.md`의 `metadata.version`을 올린다(동작 변경은 minor, 표현 변경은 patch).
- `README.md`: 사람이 읽는 소개. 무엇인지, 설치, 실행, 파서 목록만 담는다.
- `PROGRESS.md`: 지금 무엇이 동작하는가. 끝난 일의 경위는 `CHANGELOG.md`에 날짜 항목으로 적는다.
- `docs/BACKLOG.md`: 아직 하지 않은 것. 항목을 열거나 닫으면 머리의 착수 순서 표도 함께 고친다.

## 시험

- `pytest -q`로 전체 회귀 시험을 돌린다. pytest와 `requirements.txt`의 패키지가 설치된 Python을 쓴다. 시스템 기본 `python3`에 pytest가 없으면 시험이 한 건도 돌지 않으니 통과 건수를 확인한다.
- 시험은 네트워크를 쓰지 않는다. 스크립트는 `tests/_load.py`의 `load()`로 모듈처럼 읽고, 유료 파서는 `tests/cloud_cli_runner.py`로 SDK 없이 CLI 계약만 시험한다.
- 기능 추가와 버그 수정은 시험과 같은 커밋에 담는다. 표·격자를 다루는 시험 자료는 합성 PDF·이미지로 만들고 실제 문서를 저장소에 넣지 않는다.

## 코드 규칙

- `parsers/*_parse.py`와 `scripts/*.py`는 각각 혼자 실행되는 표준 Python CLI다. 파일끼리 import하지 않고 공통 패키지를 만들지 않는다.
- 도움말(`--help`)과 인자·파일 검사는 API 키 확인과 SDK 로딩보다 먼저 한다. 키나 SDK가 없는 환경에서도 사용법 오류가 먼저 보여야 한다.
- Tier 0(`pdfplumber_parse.py`)과 검증 스크립트는 틀린 결과를 내느니 실패로 닫는다. 교차 대조가 어긋난 표는 내지 않는다. 이 문턱을 낮추는 변경은 근거 문서와 함께만 한다.
- 성능을 고칠 때는 고치기 전 코드와 출력이 같은지(`before == after`)를 합성 대용량 입력으로 확인한다.
- 유료 API를 여러 번 부르는 실측은 문서 규모를 정해 승인을 받은 뒤에 한다.

## 공개 저장소

- 이 저장소는 공개다. `.env`, `references/_local.md`, `references/_changelog_local.md`, 파싱 산출물(`_work-docparse/`, `*_upstage.md` 등)은 `.gitignore`가 막고 있으니 예외를 더하지 않는다.
- 실제 문서의 이름·내용·개인 경로를 문서와 시험에 옮기지 않는다. 근거는 "63쪽 카탈로그"처럼 규모와 종류로만 적는다.
- 커밋 전에 흔적 검사(`sanitize-for-release` 스킬의 `scan_traces.py`) 결과가 0인지 확인한다.

## 커밋 흐름

- `master`에 직접 커밋하고 push한다(PR을 쓰지 않는 1인 저장소). 커밋은 경로를 지정해 묶는다.
- 여러 기기의 클론은 GitHub 원격을 정본으로 맞춘다. 파일을 직접 복사해 맞추지 않는다.
