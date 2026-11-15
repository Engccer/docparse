# -*- coding: utf-8 -*-
"""
Anthropic(Claude) 문서 파서 (docparse).

  python parsers/anthropic_parse.py <파일.pdf|.png|.jpg|.webp|.gif>
      [--model claude-opus-5-5] [--effort medium] [--pages-per-call 8]
      [--max-output 64000] [--no-fallback] [--suffix 이름]
    → <파일>_anthropic.md   (--suffix sonnet이면 <파일>_anthropic-sonnet.md)

`--suffix`는 같은 파일을 모델을 바꿔 여러 벌 판독할 때 쓴다. 없으면 두 번째 실행이 첫 결과를 지운다.

모델: 기본 `claude-opus-5-5`(2026-11-16 공식 문서 확인. 컨텍스트 1M·최대 출력 128K·
고해상도 비전). 대량·저비용은 `--model claude-sonnet-5-5` 또는 `claude-haiku-5-5`,
최난도 판독은 `--model claude-fable-5-2`. `--effort`는 low|medium|high|xhigh|max이고
기본 medium이다(Opus 5.5의 API 기본값과 같다. 이 모델은 thinking을 끌 수 없어
effort가 유일한 깊이 조절 수단이다).

⚠️ Anthropic에도 **전용 파서·OCR 엔드포인트가 없다.** Messages API에 PDF(document 블록)나
이미지(image 블록)를 넣고 범용 모델이 마크다운을 쓰게 한다(OpenAI·Gemini 파서와 같은 계열).
PDF는 API가 쪽마다 텍스트와 쪽 이미지를 함께 넣어 준다(쪽당 1,500~3,000 토큰 안팎).

⚠️ **장문 요약화 위험**이 같은 계열 파서와 같다. 그래서 PDF를 `--pages-per-call`쪽씩 잘라
여러 번 호출하고(PyMuPDF) 구간 경계를 주석으로 남긴다. `--pages-per-call 0`이면 파일 전체를
1회 호출한다(PyMuPDF 불필요. 요청당 600쪽·128MB 상한이고 장문에서는 권장하지 않는다).

⚠️ 이미지는 긴 변 2,576px(시각 토큰 4,784개)을 넘으면 API가 줄여서 본다. 작은 글자·수치표는
그 안에 들어오게 잘라서 넣는다(`scripts/image_tables.py`의 띠 조각). 이미지 하나의 상한은
base64 기준 10MB다. Office·HWPX는 Messages API가 문서로 받지 않으므로 지원하지 않는다.

거부 대체(fallback): Opus 5.5·Sonnet 5.5·Fable 계열은 안전 분류기가 요청을 거절할 수 있다.
기본으로 서버 측 `fallbacks: "default"`를 켜서 거절되면 API가 다른 Claude 모델로 같은 요청을
다시 돌린다. 그 구간을 실제로 쓴 모델을 구간 주석과 콘솔에 남긴다. 끄려면 `--no-fallback`.

실패 계약: 429·5xx·연결 오류는 SDK가 지수 백오프로 2회 재시도한다(총 3회). 구간이 하나라도
실패하거나, stop_reason이 end_turn이 아니거나(max_tokens 절단·refusal 거부 등), 전 구간이
비면 **출력 파일을 만들지 않고 종료 코드 1**. 실행 시작 시 같은 이름의 이전 출력을 지운다.

API 키: export ANTHROPIC_API_KEY_DOCPARSE="..."   (https://platform.claude.com/settings/keys)
  없으면 ANTHROPIC_API_KEY를 쓴다. 파서 전용 이름을 먼저 보는 까닭은, ANTHROPIC_API_KEY를
  셸에 두면 Claude Code 같은 도구까지 구독 대신 종량제 API로 붙기 때문이다.
"""
import os
import sys
import base64
import traceback

API_BASE = "https://api.anthropic.com"
MODEL = "claude-opus-5-5"
EFFORT = "medium"
PAGES_PER_CALL = 8
MAX_OUTPUT = 64_000
MAX_OUTPUT_LIMIT = 128_000

EFFORTS = ("low", "medium", "high", "xhigh", "max")
KEY_ENVS = ("ANTHROPIC_API_KEY_DOCPARSE", "ANTHROPIC_API_KEY")

# 서버 측 fallbacks를 받는 모델(공식 문서 기준). 그 밖의 모델에는 보내지 않는다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {
    "claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5",
}

# 요청 전체 상한 128MB. base64가 4/3로 불어나므로 원본 기준 자체 상한을 낮게 잡는다.
MAX_PDF_BYTES = 80 * 1024 * 1024
# 이미지 하나는 base64 기준 10MB → 원본 약 7.5MB.
MAX_IMAGE_BYTES = 7_400_000
IMAGE_LONG_EDGE = 2576

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
SUPPORTED_EXT = set(IMAGE_MIME) | {".pdf"}

USAGE = ("사용: python anthropic_parse.py <파일.pdf|.png|.jpg|.webp|.gif> "
         "[--model claude-opus-5-5] [--effort medium] [--pages-per-call 8] "
         "[--max-output 64000] [--no-fallback] [--suffix 이름]")

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
- 전체를 코드 블록으로 감싸지 말고, 인사말이나 작업 설명 없이 마크다운 본문만 출력하세요."""


def strip_fence(text):
    """응답 전체가 코드 펜스 하나로 감싸여 온 경우에만 벗긴다.

    본문 안의 코드 블록을 깨뜨리지 않도록 펜스가 정확히 2개(첫 줄·마지막 줄)일 때만 벗긴다.
    """
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    fences = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("```")]
    if fences != [0, len(lines) - 1] or lines[-1].strip() != "```":
        return text
    return "\n".join(lines[1:-1]).strip()


def message_markdown(message):
    """응답 Message에서 (본문, 응답 모델, 대체 여부, 출력 토큰 수) 추출. 미완료면 RuntimeError.

    거부 대체가 일어나면 content에 `fallback` 블록이 끼고, 그 앞의 글은 거절된 모델이 쓰다 만
    조각이다. 마지막 fallback 블록 뒤의 글만 본문으로 삼는다. 요청 모델이 돌지 않고 바로
    넘어간 경우에는 fallback 블록이 없으므로 `usage.iterations`의 `fallback_message`도 본다.
    """
    stop = getattr(message, "stop_reason", None)
    if stop == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) or "분류 미제공"
        raise RuntimeError(f"모델이 처리를 거부했습니다 (category={category})")
    if stop == "max_tokens":
        raise RuntimeError("출력이 max_tokens에서 잘렸습니다 (stop_reason=max_tokens)")
    if stop != "end_turn":
        raise RuntimeError(f"응답 미완료 (stop_reason={stop})")

    blocks = list(getattr(message, "content", None) or [])
    last_fallback = max((i for i, b in enumerate(blocks) if getattr(b, "type", "") == "fallback"), default=-1)
    texts = [b.text or "" for b in blocks[last_fallback + 1:] if getattr(b, "type", "") == "text"]
    usage = getattr(message, "usage", None)
    tokens = getattr(usage, "output_tokens", None)
    swapped = last_fallback >= 0 or any(
        getattr(entry, "type", "") == "fallback_message" for entry in getattr(usage, "iterations", None) or [])
    return strip_fence("\n".join(texts).strip()), getattr(message, "model", None), swapped, tokens


def call_api(client, content_block, opts):
    """구간 1건 호출 → 최종 Message. 긴 출력에서 HTTP 시간 초과를 피하려고 스트리밍으로 받는다."""
    kwargs = {
        "model": opts["model"],
        "max_tokens": opts["max_output"],
        "output_config": {"effort": opts["effort"]},
        # 공식 권고: 문서·이미지를 글보다 앞에 둔다.
        "messages": [{"role": "user", "content": [content_block, {"type": "text", "text": PROMPT}]}],
    }
    if opts["fallback"] and opts["model"] in FALLBACK_MODELS:
        stream_cm = client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    else:
        stream_cm = client.messages.stream(**kwargs)
    with stream_cm as stream:
        return stream.get_final_message()


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


def image_long_edge(path):
    """이미지 긴 변(px). PyMuPDF가 없거나 읽지 못하면 None(경고만 건너뛴다)."""
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        pix = fitz.Pixmap(path)
        return max(pix.width, pix.height)
    except Exception:
        return None


def parse_args(argv):
    """(경로, 옵션 dict) 반환. 잘못된 인자면 ValueError."""
    opts = {
        "model": MODEL, "effort": EFFORT, "pages_per_call": PAGES_PER_CALL,
        "max_output": MAX_OUTPUT, "fallback": True, "suffix": "",
    }
    path = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--no-fallback":
            opts["fallback"] = False
            i += 1
        elif a in ("--model", "--effort", "--pages-per-call", "--max-output", "--suffix"):
            if i + 1 >= len(argv):
                raise ValueError(f"{a} 값이 없습니다.")
            val = argv[i + 1]
            # 값 자리에 플래그가 오면 값을 삼킨 것이다(`--model --effort high` 류).
            if val.startswith("--"):
                raise ValueError(f"{a} 값 자리에 옵션이 왔습니다: {val}")
            if a in ("--pages-per-call", "--max-output"):
                try:
                    opts[a[2:].replace("-", "_")] = int(val)
                except ValueError:
                    raise ValueError(f"{a} 값은 정수여야 합니다: {val}")
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
    if opts["suffix"] and not all(c.isalnum() or c in "-." for c in opts["suffix"]):
        raise ValueError(f"--suffix는 글자·숫자·하이픈·마침표만 받습니다: {opts['suffix']}")
    if opts["effort"] not in EFFORTS:
        raise ValueError(f"--effort는 {'|'.join(EFFORTS)} 중 하나여야 합니다: {opts['effort']}")
    if not 1024 <= opts["max_output"] <= MAX_OUTPUT_LIMIT:
        raise ValueError(f"--max-output은 1024~{MAX_OUTPUT_LIMIT} 범위여야 합니다.")
    # 음수를 0(파일 전체 1회 호출)과 같게 취급하면 요약화 완화 기본값이 조용히 꺼진다.
    if opts["pages_per_call"] < 0:
        raise ValueError("--pages-per-call은 0 이상이어야 합니다(0 = 파일 전체를 1회 호출).")
    return path, opts


def build_chunks(path, ext, opts):
    """(구간 목록, 오류 메시지 목록). 구간은 (라벨, content_block)."""
    if ext in IMAGE_MIME:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > MAX_IMAGE_BYTES:
            return [], [
                f"오류: 이미지가 {len(data) / (1024 * 1024):.1f} MB로 API 상한(base64 10MB)을 넘습니다.",
                "  해상도·용량을 줄이거나 잘라서 다시 실행하세요.",
            ]
        return [("이미지", {"type": "image", "source": {
            "type": "base64", "media_type": IMAGE_MIME[ext],
            "data": base64.standard_b64encode(data).decode(),
        }})], []

    if opts["pages_per_call"] > 0:
        try:
            pieces = list(pdf_chunks(path, opts["pages_per_call"]))
        except ImportError:
            return [], [
                "오류: PyMuPDF를 찾을 수 없습니다. 쪽 구간 분할에 필요합니다.",
                "설치 명령: pip install PyMuPDF",
                "  또는 --pages-per-call 0 으로 파일 전체를 1회 호출(장문에서는 요약화 위험).",
            ]
        except Exception as e:
            return [], [f"오류: PDF를 열거나 쪽 구간으로 나누지 못했습니다(손상·암호 걸린 파일 여부 확인): {e}"]
    else:
        with open(path, "rb") as f:
            pieces = [(1, 0, 0, f.read())]

    if not pieces:
        return [], ["오류: PDF에 페이지가 없습니다."]

    chunks = []
    for start, end, total, data in pieces:
        label = f"p.{start}-{end}/{total}" if total else "전체"
        if len(data) > MAX_PDF_BYTES:
            return [], [
                f"오류: 구간 {label}이(가) {len(data) / (1024 * 1024):.1f} MB로 요청 상한(128MB)에 근접합니다.",
                "  --pages-per-call 값을 줄이거나 PDF 안 이미지 해상도를 낮춰 다시 실행하세요.",
            ]
        chunks.append((label, {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode(),
        }}))
    return chunks, []


def describe_error(anthropic, e):
    """SDK 예외를 한 줄 사유로. 재시도 가능 여부가 갈리는 종류를 구분해 적는다."""
    if isinstance(e, anthropic.AuthenticationError):
        return f"인증 실패(401): {KEY_ENVS[0]} 값을 확인할 것"
    if isinstance(e, anthropic.PermissionDeniedError):
        return f"권한 없음(403): {e.message}"
    if isinstance(e, anthropic.NotFoundError):
        return f"모델 또는 엔드포인트 없음(404): {e.message}"
    if isinstance(e, anthropic.RateLimitError):
        return f"한도 초과(429, 재시도 소진): {e.message}"
    if isinstance(e, anthropic.BadRequestError):
        return f"잘못된 요청(400): {e.message}"
    if isinstance(e, anthropic.APIStatusError):
        return f"HTTP {e.status_code}: {e.message}"
    if isinstance(e, anthropic.APIConnectionError):
        return f"네트워크 오류: {e}"
    return str(e)


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    try:
        path, opts = parse_args(sys.argv[1:])
    except ValueError as e:
        print(f"오류: {e}")
        return 1

    if not path:
        print(USAGE)
        print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXT))}")
        return 1
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXT:
        print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
        print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXT))}")
        print("  (Office·HWPX는 Messages API가 문서로 받지 않는다. 로컬 파서나 Upstage를 쓸 것)")
        return 1
    if not os.path.exists(path):
        print(f"오류: 파일을 찾을 수 없습니다: {path}")
        return 1

    api_key = next((os.environ[k] for k in KEY_ENVS if os.environ.get(k)), None)
    if not api_key:
        print(f"오류: {KEY_ENVS[0]} 환경 변수가 설정되지 않았습니다({KEY_ENVS[1]}도 없음).")
        print(f"설정 명령: export {KEY_ENVS[0]}=\"your-api-key\"  (Windows: setx {KEY_ENVS[0]} \"your-api-key\")")
        print("키 발급: https://platform.claude.com/settings/keys")
        return 1

    try:
        import anthropic
    except ImportError as e:
        print("오류: anthropic 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install anthropic")
        print(f"상세: {e}")
        return 1

    base = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.dirname(path)
    out_name = f"{base}_anthropic{'-' + opts['suffix'] if opts['suffix'] else ''}.md"
    out_path = os.path.join(out_dir, out_name) if out_dir else out_name
    if os.path.exists(out_path):
        os.remove(out_path)
        print(f"기존 출력 제거: {out_path}")

    use_fallback = opts["fallback"] and opts["model"] in FALLBACK_MODELS
    print(f"입력 파일: {path} ({os.path.getsize(path) / (1024 * 1024):.1f} MB)")
    print(f"모델: {opts['model']} · effort={opts['effort']} · 거부 대체={'켬' if use_fallback else '끔'}")
    if ext in IMAGE_MIME:
        edge = image_long_edge(path)
        if edge and edge > IMAGE_LONG_EDGE:
            print(f"경고: 이미지 긴 변이 {edge}px이다. API가 {IMAGE_LONG_EDGE}px로 줄여서 보므로 작은 글자가 뭉개질 수 있다.")
            print("  수치표·작은 글자는 잘라서(띠 조각) 넣을 것.")

    chunks, errors = build_chunks(path, ext, opts)
    if errors:
        for line in errors:
            print(line)
        return 1

    print(f"변환 중... 구간 {len(chunks)}개 = API 호출 {len(chunks)}회")
    # base_url을 고정한다. 비워 두면 SDK가 ANTHROPIC_BASE_URL을 읽어, 셸이 게이트웨이·프록시를
    # 가리킬 때 파서 전용 키가 그쪽으로 나간다.
    client = anthropic.Anthropic(api_key=api_key, base_url=API_BASE)

    parts, empty, failed, swapped, out_tokens = [], [], [], [], 0
    for label, content_block in chunks:
        print(f"  [{label}] 호출 중...")
        try:
            message = call_api(client, content_block, opts)
            body, served, was_swapped, tokens = message_markdown(message)
        except anthropic.APIError as e:
            reason = describe_error(anthropic, e)
            print(f"  [{label}] 실패: {reason}")
            failed.append((label, reason))
            continue
        except RuntimeError as e:
            print(f"  [{label}] 실패: {e}")
            failed.append((label, str(e)))
            continue
        if tokens:
            out_tokens += tokens
        if not body:
            empty.append(label)
        marker = label
        if was_swapped or (served and served != opts["model"]):
            served = served or "모델 미상"
            swapped.append((label, served))
            marker = f"{label} · 대체 모델 {served}"
            print(f"  [{label}] 요청 모델이 거절해 {served}가 대신 처리했습니다.")
        parts.append(f"<!-- {marker} -->\n\n{body}")
        print(f"  [{label}] {len(body)}글자 (출력 토큰 {tokens if tokens is not None else '?'})")

    if failed:
        print(f"오류: 구간 {len(chunks)}개 중 {len(failed)}개 실패. 출력 파일을 만들지 않았습니다.")
        for label, reason in failed:
            print(f"  - {label}: {reason[:200]}")
        print("→ 절단(max_tokens)이면 --pages-per-call을 줄이거나 --max-output을 올릴 것.")
        print(f"→ 한도(429)면 잠시 후 재실행, 인증(401)이면 {KEY_ENVS[0]} 확인.")
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
    if swapped:
        print(f"참고: 대체 모델이 처리한 구간 {len(swapped)}개: "
              + ", ".join(f"{label}→{served}" for label, served in swapped[:20]))
    print("확인 권고: 범용 LLM 파서라 장문에서 요약화 위험이 있다. 구간 경계 주석을 기준으로")
    print("  원문 쪽수와 분량을 대조하고, 표는 다른 파서와 교차검증할 것.")
    print(f"출력 파일: {out_path}")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # Windows cp949 콘솔에서도 한글 출력이 깨지지 않게
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if __doc__ and any(_arg in ("--help", "-h") for _arg in sys.argv[1:]):
        print(__doc__.strip())
        sys.exit(0)
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
