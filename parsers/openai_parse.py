# -*- coding: utf-8 -*-
"""
OpenAI 문서 파서 (docparse).

  python parsers/openai_parse.py <파일.pdf|.png|.jpg|.webp|.gif|.docx|.pptx|.xlsx>
      [--model gpt-5.6-terra] [--effort medium] [--detail auto]
      [--pages-per-call 8] [--max-output 32768] [--verbosity high]
    → <파일>_openai.md

모델: 기본 `gpt-5.6-terra`(2026-09-03 기준 GPT-5.6 계열 중간 티어. 컨텍스트 1,050,000·
최대 출력 128,000·입력 text+image·reasoning.effort none|low|medium|high|xhigh|max).
저비용 대량 처리는 `--model gpt-5.6-luna`, 최난도 스캔은 `--model gpt-5.6-sol`.

⚠️ OpenAI에는 **전용 파서·OCR 엔드포인트가 없다.** 문서 파싱은 Responses API(/v1/responses)에
PDF·이미지를 넣고 범용 멀티모달 모델이 마크다운을 쓰게 하는 방식이다(Upstage·Mistral 같은
전용 파서와 성격이 다르고, Gemini 파서와 같은 계열이다). PDF는 API가 텍스트 레이어와 쪽
이미지를 함께 넣어 준다.

⚠️ **장문 요약화 위험이 Gemini와 같은 계열이다.** 범용 LLM은 긴 입력에서 전사 대신 요약으로
빠져 본문을 조용히 버릴 수 있다. 그래서 이 파서는 기본적으로 PDF를 `--pages-per-call`쪽씩
잘라 여러 번 호출하고(PyMuPDF로 쪽 구간 PDF를 만들어 보낸다), 구간 경계를 주석으로 남긴다.
`--pages-per-call 0`이면 파일 전체를 1회 호출한다(PyMuPDF 불필요, 장문에서는 권장하지 않음).

⚠️ Office(.docx·.pptx·.xlsx)는 API가 받되 **텍스트만 추출하고 쪽 이미지·도표를 보지 않는다.**
품질은 로컬 결정론 파서(docx_local·xlsx_local)가 낫지만 그것은 등급이지 입력 경계가 아니므로,
받을 수 있는 형식은 받아 둔다(로컬 파서가 텍스트박스·각주 등으로 거부·승격할 때의 후보).
HWPX는 API가 형식 자체를 모르므로 지원하지 않는다.

실패 계약: 호출이 429·5xx면 지수 백오프로 최대 2회 재시도(총 3회). 구간이 하나라도 실패하거나,
응답 status가 completed가 아니거나(출력 토큰 상한 도달 등 절단), 거부 응답이거나, 전 구간이
비면 **출력 파일을 만들지 않고 종료 코드 1**. 실행 시작 시 같은 이름의 이전 출력을 지운다.

API 키: export OPENAI_API_KEY="..."   (https://platform.openai.com/api-keys)
"""
import os
import sys
import json
import base64
import time
import urllib.request
import urllib.error
import traceback

API_URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-5.6-terra"
EFFORT = "medium"
DETAIL = "auto"
VERBOSITY = "high"        # 전사 작업에서 문자 그대로에 가깝게 쓰게 한다(공식 쿡북 권고)
PAGES_PER_CALL = 8
MAX_OUTPUT = 32_768
TIMEOUT = 300

RETRY_MAX = 3
RETRY_STATUS = {429, 500, 502, 503, 504}

EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
VERBOSITIES = ("low", "medium", "high")
# PDF(input_file)는 auto|low|high만 받는다. original은 이미지(input_image) 전용이다.
DETAILS_FILE = ("auto", "low", "high")
DETAILS_IMAGE = ("auto", "low", "high", "original")

# 요청당 파일 50MB 상한. base64 인코딩 전 원본 기준으로 여유를 두고 자체 상한을 잡는다.
MAX_CHUNK_BYTES = 32 * 1024 * 1024

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# Office 문서도 API가 받지만 **텍스트만 추출하고 쪽 이미지를 보지 않는다**(공식 문서).
# 품질은 로컬 결정론 파서(docx_local·xlsx_local)가 낫지만, 그것은 등급이지 입력 경계가
# 아니므로 받을 수 있는 형식은 받는다(로컬 파서가 거부·승격할 때 이 파서가 후보로 남는다).
OFFICE_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
SUPPORTED_EXT = set(IMAGE_MIME) | set(OFFICE_MIME) | {".pdf"}

PROMPT = """당신은 문서에서 데이터를 정밀하게 추출하는 전문 문서 파싱 엔지니어입니다. 주어진 문서를 마크다운으로 변환하세요.

[최우선 원칙]
- 이것은 요약 작업이 아니라 전사 작업입니다. 어떤 문장도 요약·생략·재서술하지 말고 원문 그대로 옮기세요.
- 분량이 많아도 중간에 "이하 생략", "동일 형식 반복" 같은 축약을 쓰지 마세요.
- 주어진 범위의 모든 쪽을 처음부터 끝까지 다루세요.

[구조]
- 제목·본문·목록 등 문서 구조를 마크다운으로 표현하세요.
- 머리말·꼬리말·쪽 번호는 본문에 섞지 말고 생략하세요.
- 이미지·도형은 [이미지: 설명] 형식으로 그 자리에 표시하세요.

[표]
- 표는 마크다운 표로 변환하세요.
- 병합된 셀은 해당되는 모든 행에 값을 반복 기재하세요.
- 빈 셀은 '-'로 표기하여 누락과 구분하세요.
- 셀 안의 텍스트와 숫자를 있는 그대로 보존하세요.

[그 밖에]
- 문서에 합계·일수·시수 등 요약 통계가 있으면 빠짐없이 기재하세요.
- 범례·주석·각주도 누락 없이 추출하세요.
- 식별이 불확실한 텍스트는 추측하지 말고 '(식별 불확실)'로 표기하세요.
- 전체를 코드 블록으로 감싸지 말고 마크다운 본문만 출력하세요."""


def call_api(content_part, api_key, opts):
    """구간 1건 호출 → 응답 dict. 429·5xx는 백오프 재시도. 실패 시 RuntimeError."""
    body = json.dumps({
        "model": opts["model"],
        "input": [{
            "role": "user",
            "content": [{"type": "input_text", "text": PROMPT}, content_part],
        }],
        "reasoning": {"effort": opts["effort"]},
        "text": {"verbosity": opts["verbosity"]},
        "max_output_tokens": opts["max_output"],
        "store": False,
    }).encode()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        req = urllib.request.Request(API_URL, data=body, headers=headers)
        try:
            return json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.read().decode(errors='replace')[:300]}"
            if e.code in RETRY_STATUS and attempt < RETRY_MAX:
                wait = 2 ** attempt
                print(f"  재시도 {attempt}/{RETRY_MAX - 1} (HTTP {e.code}), {wait}초 대기")
                time.sleep(wait)
                continue
            raise RuntimeError(last_err)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = f"네트워크 오류 {e}"
            if attempt < RETRY_MAX:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(last_err)
    raise RuntimeError(last_err or "알 수 없는 오류")


def strip_fence(text):
    """응답 전체가 코드 펜스 하나로 감싸여 온 경우에만 벗긴다(마크다운이 코드로 굳는 것 방지).

    ⚠️ 본문 안의 코드 블록을 깨뜨리지 않으려면 **감싼 펜스임이 확실할 때만** 벗겨야 한다.
    시작·끝이 ```라는 이유만으로 첫/마지막 줄을 자르면, 코드 블록으로 시작해 코드 블록으로
    끝나는 정상 본문에서 여는 펜스와 닫는 펜스가 하나씩 사라져 이후 렌더가 통째로 어긋난다.
    그래서 펜스가 정확히 2개(여는 것 하나, 닫는 것 하나)일 때만 벗긴다.
    """
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    fences = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("```")]
    if fences != [0, len(lines) - 1] or lines[-1].strip() != "```":
        return text
    return "\n".join(lines[1:-1]).strip()


def response_markdown(resp):
    """응답에서 (본문, 거부 사유 목록, 출력 토큰 수) 추출. 미완료 응답은 RuntimeError."""
    status = resp.get("status")
    if status and status != "completed":
        reason = (resp.get("incomplete_details") or {}).get("reason") or "사유 미제공"
        raise RuntimeError(f"응답 미완료 (status={status}, reason={reason})")
    if resp.get("error"):
        raise RuntimeError(f"API 오류: {json.dumps(resp['error'], ensure_ascii=False)[:200]}")

    texts, refusals = [], []
    for item in resp.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text":
                texts.append(part.get("text") or "")
            elif part.get("type") == "refusal":
                refusals.append(part.get("refusal") or "거부")
    tokens = (resp.get("usage") or {}).get("output_tokens")
    return strip_fence("\n".join(texts).strip()), refusals, tokens


def pdf_chunks(path, pages_per_call):
    """PDF를 pages_per_call쪽 구간 PDF로 잘라 (시작쪽, 끝쪽, 전체쪽수, bytes)를 낸다."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    src = fitz.open(path)
    try:
        total = len(src)
        step = pages_per_call if pages_per_call > 0 else max(total, 1)
        for start in range(0, total, step):
            end = min(start + step, total) - 1
            out = fitz.open()
            try:
                out.insert_pdf(src, from_page=start, to_page=end)
                yield start + 1, end + 1, total, out.tobytes()
            finally:
                out.close()
    finally:
        src.close()


def parse_args(argv):
    """(경로, 옵션 dict) 반환. 잘못된 인자면 ValueError."""
    opts = {
        "model": MODEL, "effort": EFFORT, "detail": DETAIL, "verbosity": VERBOSITY,
        "pages_per_call": PAGES_PER_CALL, "max_output": MAX_OUTPUT,
    }
    path = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--model", "--effort", "--detail", "--verbosity", "--pages-per-call", "--max-output"):
            if i + 1 >= len(argv):
                raise ValueError(f"{a} 값이 없습니다.")
            val = argv[i + 1]
            # 값 자리에 플래그가 오면 값을 삼킨 것이다(`--model --effort high` 류).
            if val.startswith("--"):
                raise ValueError(f"{a} 값 자리에 옵션이 왔습니다: {val}")
            if a == "--pages-per-call":
                opts["pages_per_call"] = int(val)
            elif a == "--max-output":
                opts["max_output"] = int(val)
            else:
                opts[a[2:]] = val
            i += 2
        elif a.startswith("--"):
            raise ValueError(f"알 수 없는 옵션: {a}")
        else:
            # 파일을 둘 이상 주면 마지막 것이 조용히 이기고 앞 파일은 파싱되지 않는다.
            if path is not None:
                raise ValueError(f"파일은 한 번에 하나만 받습니다: {path}, {a}")
            path = a
            i += 1
    if opts["effort"] not in EFFORTS:
        raise ValueError(f"--effort는 {'|'.join(EFFORTS)} 중 하나여야 합니다: {opts['effort']}")
    if opts["verbosity"] not in VERBOSITIES:
        raise ValueError(f"--verbosity는 {'|'.join(VERBOSITIES)} 중 하나여야 합니다: {opts['verbosity']}")
    if opts["max_output"] < 1024:
        raise ValueError("--max-output은 1024 이상이어야 합니다.")
    # 음수를 0(파일 전체 1회 호출)과 같게 취급하면 요약화 완화 기본값이 조용히 꺼진다.
    if opts["pages_per_call"] < 0:
        raise ValueError("--pages-per-call은 0 이상이어야 합니다(0 = 파일 전체를 1회 호출).")
    return path, opts


def too_big(data, label):
    """요청 상한(50MB)에 근접하면 오류 메시지 목록, 아니면 빈 목록."""
    if len(data) <= MAX_CHUNK_BYTES:
        return []
    return [
        f"오류: {label}이(가) {len(data) / (1024 * 1024):.1f} MB로 요청 상한(50MB)에 근접합니다.",
        "  PDF면 --pages-per-call 값을 줄이고, 단일 파일이면 해상도·용량을 줄여 다시 실행하세요.",
    ]


def build_chunks(path, ext, base, opts):
    """(구간 목록, 오류 메시지 목록). 구간은 (라벨, content_part)."""
    if ext in IMAGE_MIME:
        with open(path, "rb") as f:
            data = f.read()
        err = too_big(data, "이미지")
        if err:
            return [], err
        uri = f"data:{IMAGE_MIME[ext]};base64," + base64.b64encode(data).decode()
        return [("이미지", {"type": "input_image", "image_url": uri, "detail": opts["detail"]})], []

    if ext in OFFICE_MIME:
        with open(path, "rb") as f:
            data = f.read()
        err = too_big(data, "파일")
        if err:
            return [], err
        # 쪽 이미지가 없는 경로라 detail은 의미가 없다(보내지 않는다).
        uri = f"data:{OFFICE_MIME[ext]};base64," + base64.b64encode(data).decode()
        return [("전체", {"type": "input_file", "filename": base + ext, "file_data": uri})], []

    if opts["pages_per_call"] > 0:
        try:
            pieces = list(pdf_chunks(path, opts["pages_per_call"]))
        except ImportError:
            return [], [
                "오류: PyMuPDF를 찾을 수 없습니다. 쪽 구간 분할에 필요합니다.",
                "설치 명령: pip install PyMuPDF",
                "  또는 --pages-per-call 0 으로 파일 전체를 1회 호출(장문에서는 요약화 위험).",
            ]
    else:
        with open(path, "rb") as f:
            pieces = [(1, 0, 0, f.read())]

    if not pieces:
        return [], ["오류: PDF에 페이지가 없습니다."]

    chunks = []
    for start, end, total, data in pieces:
        label = f"p.{start}-{end}/{total}" if total else "전체"
        err = too_big(data, f"구간 {label}")
        if err:
            return [], err
        uri = "data:application/pdf;base64," + base64.b64encode(data).decode()
        chunks.append((label, {
            "type": "input_file",
            "filename": f"{base}.pdf",
            "file_data": uri,
            "detail": opts["detail"],
        }))
    return chunks, []


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    try:
        path, opts = parse_args(sys.argv[1:])
    except ValueError as e:
        print(f"오류: {e}")
        return 1

    if not path:
        print("사용: python openai_parse.py <파일.pdf|.png|.jpg|.webp|.gif|.docx|.pptx|.xlsx> "
              "[--model gpt-5.6-terra] [--effort medium] [--detail auto] "
              "[--pages-per-call 8] [--max-output 32768] [--verbosity high]")
        print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXT))}")
        return 1
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXT:
        print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
        print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXT))}")
        print("  (HWPX는 API가 형식을 모른다. hwpx_local·Upstage를 쓸 것)")
        return 1
    if not os.path.exists(path):
        print(f"오류: 파일을 찾을 수 없습니다: {path}")
        return 1

    if ext in IMAGE_MIME:
        allowed_detail = DETAILS_IMAGE
    elif ext == ".pdf":
        allowed_detail = DETAILS_FILE
    else:
        allowed_detail = None      # Office는 쪽 이미지가 없어 detail 자체가 없다
    if allowed_detail and opts["detail"] not in allowed_detail:
        print(f"오류: {ext} 입력의 --detail은 {'|'.join(allowed_detail)} 중 하나여야 합니다: {opts['detail']}")
        if opts["detail"] == "original":
            print("  (original은 이미지 입력 전용이다. PDF는 auto|low|high)")
        return 1

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("오류: OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export OPENAI_API_KEY=\"your-api-key\"  (Windows: setx OPENAI_API_KEY \"your-api-key\")")
        print("키 발급: https://platform.openai.com/api-keys")
        return 1

    base = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.dirname(path)
    out_path = os.path.join(out_dir, f"{base}_openai.md") if out_dir else f"{base}_openai.md"
    if os.path.exists(out_path):
        os.remove(out_path)
        print(f"기존 출력 제거: {out_path}")

    print(f"입력 파일: {path} ({os.path.getsize(path) / (1024 * 1024):.1f} MB)")
    detail_shown = opts["detail"] if allowed_detail else "해당 없음"
    print(f"모델: {opts['model']} · effort={opts['effort']} · detail={detail_shown} · verbosity={opts['verbosity']}")
    if ext in OFFICE_MIME:
        print("경고: Office 문서는 API가 **텍스트만 추출**하고 쪽 이미지·도표를 보지 않는다.")
        print("  로컬 결정론 파서(docx_local·xlsx_local)가 검증까지 붙여 더 잘하니, 그쪽이 거부할 때 쓸 것.")

    chunks, errors = build_chunks(path, ext, base, opts)
    if errors:
        for line in errors:
            print(line)
        return 1

    print(f"변환 중... 구간 {len(chunks)}개 = API 호출 {len(chunks)}회")

    parts, empty, failed, out_tokens = [], [], [], 0
    for label, content_part in chunks:
        print(f"  [{label}] 호출 중...")
        try:
            resp = call_api(content_part, api_key, opts)
            body, refusals, tokens = response_markdown(resp)
        except RuntimeError as e:
            print(f"  [{label}] 실패: {e}")
            failed.append((label, str(e)))
            continue
        if refusals:
            print(f"  [{label}] 모델이 처리를 거부했습니다: {refusals[0][:120]}")
            failed.append((label, f"거부: {refusals[0][:120]}"))
            continue
        if tokens:
            out_tokens += tokens
        if not body:
            empty.append(label)
        parts.append(f"<!-- {label} -->\n\n{body}")
        print(f"  [{label}] {len(body)}글자 (출력 토큰 {tokens if tokens is not None else '?'})")

    if failed:
        print(f"오류: 구간 {len(chunks)}개 중 {len(failed)}개 실패. 출력 파일을 만들지 않았습니다.")
        for label, reason in failed:
            print(f"  - {label}: {reason[:160]}")
        print("→ 절단(max_output_tokens)이면 --pages-per-call을 줄이거나 --max-output을 올릴 것.")
        print("→ 한도(429)면 잠시 후 재실행, 인증(401)이면 OPENAI_API_KEY 확인.")
        return 1
    if len(empty) == len(chunks):
        print("오류: 모든 구간의 결과가 비어 있습니다. 출력 파일을 만들지 않았습니다.")
        return 1

    content = "\n\n---\n\n".join(parts)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"변환 완료! {len(chunks)}구간, {len(content)}글자가 저장되었습니다. (출력 토큰 합계 {out_tokens})")
    if empty:
        print(f"경고: 내용이 빈 구간 {len(empty)}개: {', '.join(empty[:20])}")
        print("  (백지·그림 전용 구간이면 정상. 본문이 있으면 다른 파서로 그 구간을 보완할 것)")
    print("확인 권고: 범용 LLM 파서라 장문에서 요약화 위험이 있다. 구간 경계 주석을 기준으로")
    print("  원문 쪽수와 분량을 대조하고, 표는 다른 파서와 교차검증할 것.")
    print(f"출력 파일: {out_path}")
    return 0


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except Exception as e:
        print(f"\n오류 발생: {e}")
        print("\n상세 정보:")
        traceback.print_exc()

    # 비-TTY(에이전트·파이프·백그라운드)에서 input()이 무한 블록되지 않도록 가드.
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nEnter를 눌러 종료...")
        except EOFError:
            pass
    sys.exit(exit_code)
