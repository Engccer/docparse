# -*- coding: utf-8 -*-
"""
Azure Document Intelligence 파서 (docparse).

  python parsers/azure_parse.py <파일.pdf|.png|.jpg|.bmp|.tiff|.heif|.docx|.xlsx|.pptx|.html>
      [--model prebuilt-layout] [--high-res] [--features a,b] [--pages 1-3,5]
      [--locale ko] [--json]
    → <파일>_azure.md   (--json이면 <파일>_azure.json도 함께)

설정(2026-11-16 공식 문서 확인): REST API `2024-11-30`(v4.0 GA, 그보다 새 GA·preview 없음),
모델 `prebuilt-layout`, `outputContentFormat=markdown`. LLM이 아닌 전용 OCR·레이아웃 엔진이라
요약화 위험이 없고 단어마다 보정된 confidence를 준다. 한국어 인쇄체·손글씨를 지원한다.

출력 마크다운의 모양: 표는 HTML `<table>`(rowspan·colspan 보존), 쪽 경계는 `<!-- PageBreak -->`,
머리말·꼬리말·쪽 번호는 `<!-- PageHeader="..." -->` 류 주석, 그림은 `<figure>`. 가공하지 않고
서비스가 준 그대로 저장한다.

옵션:
  --model      prebuilt-layout(기본. 표·구조·마크다운) 또는 prebuilt-read(글자만. 마크다운 출력이
               없어 일반 텍스트로 저장된다. 1,000쪽당 요금이 layout의 약 1/7).
  --high-res   add-on `ocrHighResolution`. 작은 글자·도면·수치표 이미지용. 추가 요금이 붙는다.
  --features   add-on을 쉼표로 직접 지정(ocrHighResolution, formulas, styleFont, barcodes,
               languages, keyValuePairs). add-on은 PDF·이미지에서만 된다(Office·HTML 불가).
  --pages      처리할 쪽("1-3,5,7-9", 1부터). PDF·TIFF에서만 의미가 있다.
  --locale     언어 힌트(ko, en-US 등). 기본은 자동 판별.
  --json       서비스 응답 analyzeResult 전체를 <파일>_azure.json으로 저장(단어 confidence·
               좌표·손글씨 여부 `styles[].isHandwritten`을 후속 검증에 쓸 때).

요금·한도(S0, 한국 중부 기준): layout 1,000쪽당 $10, read $1.50, 고해상도 add-on +$6.
파일 500MB·2,000쪽. ⚠️ 무료 등급(F0)은 파일 4MB에 **문서의 처음 2쪽만 처리**한다.

실패 계약: 429·5xx는 지수 백오프(Retry-After 우선)로 최대 2회 재시도(분석 요청의 시간 초과는 이중 과금을 피하려 재전송하지 않는다). 분석이 failed·canceled로
끝나거나, 제한 시간 안에 끝나지 않거나, 결과가 비거나, PDF·TIFF 쪽수(PyMuPDF)와 처리된 쪽수가
다르면(F0의 2쪽 절단 등) **출력 파일을 만들지 않고 종료 코드 1**. 실행 시작 시 같은 이름의
이전 출력을 지운다.

환경 변수(둘 다 필요):
  export AZURE_DOCINTEL_API_KEY_DOCPARSE="..."
  export AZURE_DOCINTEL_ENDPOINT_DOCPARSE="https://<리소스이름>.cognitiveservices.azure.com/"
  없으면 Microsoft 빠른 시작의 이름 DOCUMENTINTELLIGENCE_API_KEY·DOCUMENTINTELLIGENCE_ENDPOINT를 쓴다.
  리소스 만들기: az cognitiveservices account create --kind FormRecognizer --sku S0 ...
  (https://portal.azure.com → Document Intelligence)
"""
import os
import sys
import json
import base64
import time
import urllib.parse
import urllib.request
import urllib.error
import traceback

API_VERSION = "2024-11-30"
MODEL = "prebuilt-layout"
MODELS = ("prebuilt-layout", "prebuilt-read")
FEATURES = ("ocrHighResolution", "formulas", "styleFont", "barcodes", "languages", "keyValuePairs")

KEY_ENVS = ("AZURE_DOCINTEL_API_KEY_DOCPARSE", "DOCUMENTINTELLIGENCE_API_KEY")
ENDPOINT_ENVS = ("AZURE_DOCINTEL_ENDPOINT_DOCPARSE", "DOCUMENTINTELLIGENCE_ENDPOINT")

TIMEOUT = 120             # 요청 1건
POLL_DEADLINE = 900       # 분석 완료 대기 한도(초)
POLL_DEFAULT = 2
RETRY_MAX = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_BYTES = 500 * 1024 * 1024
LOW_CONFIDENCE = 0.8

PAGED_EXT = {".pdf", ".tif", ".tiff"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".heif"}
OFFICE_EXT = {".docx", ".xlsx", ".pptx", ".html"}
SUPPORTED_EXT = IMAGE_EXT | OFFICE_EXT | {".pdf"}

USAGE = ("사용: python azure_parse.py <파일.pdf|.png|.jpg|.bmp|.tiff|.heif|.docx|.xlsx|.pptx|.html> "
         "[--model prebuilt-layout] [--high-res] [--features a,b] [--pages 1-3,5] [--locale ko] [--json]")


def request(url, api_key, body=None):
    """요청 1건 → (본문 bytes, 응답 헤더). 429·5xx·연결 오류는 백오프 재시도. 실패 시 RuntimeError."""
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.read().decode(errors='replace')[:400]}"
            if e.code in RETRY_STATUS and attempt < RETRY_MAX:
                wait = retry_after(e.headers, 2 ** attempt)
                print(f"  재시도 {attempt}/{RETRY_MAX - 1} (HTTP {e.code}), {wait}초 대기")
                time.sleep(wait)
                continue
            raise RuntimeError(last_err)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = f"네트워크 오류 {e}"
            # 분석 요청(POST)은 다시 보내지 않는다. 서버가 이미 받았다면 두 번 접수·과금된다.
            if body is None and attempt < RETRY_MAX:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(last_err)
    raise RuntimeError(last_err or "알 수 없는 오류")


def retry_after(headers, default):
    """Retry-After 헤더(초). 없거나 이상하면 default. 1~60초로 자른다."""
    try:
        return max(1, min(60, int(headers.get("Retry-After"))))
    except (TypeError, ValueError):
        return default


def analyze_url(endpoint, opts):
    query = {"api-version": API_VERSION}
    if opts["model"] == "prebuilt-layout":
        query["outputContentFormat"] = "markdown"
    if opts["features"]:
        query["features"] = ",".join(opts["features"])
    if opts["pages"]:
        query["pages"] = opts["pages"]
    if opts["locale"]:
        query["locale"] = opts["locale"]
    return (f"{endpoint.rstrip('/')}/documentintelligence/documentModels/"
            f"{opts['model']}:analyze?{urllib.parse.urlencode(query)}")


def analyze(path, endpoint, api_key, opts):
    """분석 요청 → 폴링 → analyzeResult dict. 실패 시 RuntimeError."""
    with open(path, "rb") as f:
        body = json.dumps({"base64Source": base64.b64encode(f.read()).decode()}).encode()
    _, headers = request(analyze_url(endpoint, opts), api_key, body)
    op_url = headers.get("Operation-Location")
    if not op_url:
        raise RuntimeError("응답에 Operation-Location 헤더가 없습니다.")
    # 결과 URL은 요청을 보낸 리소스와 같은 호스트여야 한다(키를 다른 곳에 보내지 않는다).
    if urllib.parse.urlsplit(op_url).netloc.lower() != urllib.parse.urlsplit(endpoint).netloc.lower():
        raise RuntimeError(f"Operation-Location 호스트가 엔드포인트와 다릅니다: {op_url[:120]}")

    deadline = time.monotonic() + POLL_DEADLINE
    wait = retry_after(headers, POLL_DEFAULT)
    while True:
        time.sleep(wait)
        raw, poll_headers = request(op_url, api_key)
        try:
            result = json.loads(raw)
            status = result.get("status")
        except (ValueError, AttributeError):
            raise RuntimeError(f"결과 응답을 해석하지 못했습니다: {raw[:200]!r}")
        if status == "succeeded":
            return result.get("analyzeResult") or {}
        if status in ("failed", "canceled"):
            err = json.dumps(result.get("error") or {}, ensure_ascii=False)[:400]
            raise RuntimeError(f"분석 {status}: {err}")
        if time.monotonic() > deadline:
            raise RuntimeError(f"분석이 {POLL_DEADLINE}초 안에 끝나지 않았습니다 (status={status})")
        wait = retry_after(poll_headers, POLL_DEFAULT)


def pdf_page_count(path):
    """PDF·여러 쪽 TIFF의 쪽수. PyMuPDF가 없거나 열지 못하면 None."""
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        with fitz.open(path) as doc:
            return len(doc)
    except Exception:
        return None


def expected_pages(total, spec):
    """--pages 지정("1-3,5")이 고르는 쪽 수. 지정이 없으면 total. 해석 못 하면 None."""
    if not spec:
        return total
    chosen = set()
    try:
        for part in spec.split(","):
            lo, _, hi = part.strip().partition("-")
            chosen.update(range(int(lo), int(hi or lo) + 1))
    except ValueError:
        return None
    return len({p for p in chosen if 1 <= p <= total})


def confidence_report(result):
    """(단어 수, 평균 confidence, 저신뢰 단어 [(쪽, 글자, 값)], 손글씨 구간 수)."""
    words, low = [], []
    for page in result.get("pages") or []:
        for w in page.get("words") or []:
            c = w.get("confidence")
            if c is None:
                continue
            words.append(c)
            if c < LOW_CONFIDENCE:
                low.append((page.get("pageNumber"), w.get("content", ""), c))
    # 인쇄 문서의 대시 한 글자가 confidence 0.3으로 손글씨 판정되는 일이 있어 낮은 판정은 세지 않는다.
    handwritten = sum(1 for s in result.get("styles") or []
                      if s.get("isHandwritten") and (s.get("confidence") or 0) >= 0.5)
    mean = sum(words) / len(words) if words else None
    return len(words), mean, low, handwritten


def parse_args(argv):
    """(경로, 옵션 dict) 반환. 잘못된 인자면 ValueError."""
    opts = {"model": MODEL, "features": [], "pages": None, "locale": None, "json": False}
    path = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--high-res":
            opts["features"].append("ocrHighResolution")
            i += 1
        elif a == "--json":
            opts["json"] = True
            i += 1
        elif a in ("--model", "--features", "--pages", "--locale"):
            if i + 1 >= len(argv):
                raise ValueError(f"{a} 값이 없습니다.")
            val = argv[i + 1]
            if val.startswith("--"):
                raise ValueError(f"{a} 값 자리에 옵션이 왔습니다: {val}")
            if a == "--features":
                opts["features"] += [v.strip() for v in val.split(",") if v.strip()]
            else:
                opts[a[2:]] = val
            i += 2
        elif a.startswith("--"):
            raise ValueError(f"알 수 없는 옵션: {a}")
        else:
            if path is not None:
                raise ValueError(f"파일은 한 번에 하나만 받습니다: {path}, {a}")
            path = a
            i += 1
    if opts["model"] not in MODELS:
        raise ValueError(f"--model은 {'|'.join(MODELS)} 중 하나여야 합니다: {opts['model']}")
    opts["features"] = list(dict.fromkeys(opts["features"]))
    bad = [f for f in opts["features"] if f not in FEATURES]
    if bad:
        raise ValueError(f"알 수 없는 add-on: {', '.join(bad)} (가능: {', '.join(FEATURES)})")
    if opts["pages"] and not all(c.isdigit() or c in "-, " for c in opts["pages"]):
        raise ValueError(f"--pages는 \"1-3,5\" 형식이어야 합니다: {opts['pages']}")
    return path, opts


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
        print("  (HWPX는 서비스가 형식을 모른다. hwpx_local·Upstage를 쓸 것)")
        return 1
    if not os.path.exists(path):
        print(f"오류: 파일을 찾을 수 없습니다: {path}")
        return 1
    if ext in OFFICE_EXT and opts["features"]:
        print(f"오류: add-on({', '.join(opts['features'])})은 PDF·이미지에서만 됩니다. Office·HTML에는 쓸 수 없습니다.")
        return 1
    if ext in OFFICE_EXT and opts["pages"]:
        print("오류: --pages는 Office·HTML 입력에서 지원되지 않습니다.")
        return 1
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        print(f"오류: 파일이 {size / (1024 * 1024):.0f} MB로 서비스 상한(500MB)을 넘습니다.")
        return 1

    # 키와 엔드포인트는 같은 이름 짝에서만 고른다(한 리소스의 키가 다른 리소스로 가지 않게).
    api_key, endpoint = next(((os.environ[k], os.environ[e]) for k, e in zip(KEY_ENVS, ENDPOINT_ENVS)
                              if os.environ.get(k) and os.environ.get(e)), (None, None))
    if not api_key:
        missing = [n for n in (KEY_ENVS[0], ENDPOINT_ENVS[0]) if not os.environ.get(n)]
        print(f"오류: 환경 변수가 설정되지 않았습니다: {', '.join(missing)}")
        print(f"설정 명령: export {KEY_ENVS[0]}=\"your-key\"")
        print(f"          export {ENDPOINT_ENVS[0]}=\"https://<리소스이름>.cognitiveservices.azure.com/\"")
        print("리소스 만들기: https://portal.azure.com → Document Intelligence (또는 az cognitiveservices account create --kind FormRecognizer)")
        return 1
    if not endpoint.lower().startswith("https://"):
        print(f"오류: 엔드포인트는 https:// 로 시작해야 합니다: {endpoint}")
        return 1

    base = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.dirname(path)
    out_path = os.path.join(out_dir, f"{base}_azure.md") if out_dir else f"{base}_azure.md"
    json_path = out_path[:-3] + ".json"
    for stale in (out_path, json_path):
        if os.path.exists(stale):
            os.remove(stale)
            print(f"기존 출력 제거: {stale}")

    print(f"입력 파일: {path} ({size / (1024 * 1024):.1f} MB)")
    print(f"모델: {opts['model']} · API {API_VERSION} · add-on={','.join(opts['features']) or '없음'}"
          f"{' · 쪽 ' + opts['pages'] if opts['pages'] else ''}")
    if opts["model"] == "prebuilt-read":
        print("참고: prebuilt-read는 마크다운 출력이 없다. 표·제목 구조 없이 일반 텍스트로 저장된다.")
    if ext in OFFICE_EXT:
        print("참고: Office·HTML은 문서 안 이미지를 분석하지 않는다(텍스트·구조만).")

    print("분석 중...")
    try:
        result = analyze(path, endpoint, api_key, opts)
    except RuntimeError as e:
        print(f"오류: {e}")
        print("출력 파일을 만들지 않았습니다.")
        print(f"→ 인증(401)이면 {KEY_ENVS[0]}·{ENDPOINT_ENVS[0]} 확인, 한도(429)면 잠시 후 재실행.")
        print("→ 무료 등급(F0)은 4MB를 넘는 파일을 받지 않는다.")
        return 1

    content = (result.get("content") or "").strip()
    done_pages = len(result.get("pages") or [])
    if not content:
        print("오류: 결과가 비어 있습니다. 출력 파일을 만들지 않았습니다.")
        return 1

    if ext in PAGED_EXT:
        total = pdf_page_count(path)
        want = expected_pages(total, opts["pages"]) if total is not None else None
        if want is not None and done_pages != want:
            print(f"오류: 처리된 쪽수({done_pages})가 기대 쪽수({want})와 다릅니다. 출력 파일을 만들지 않았습니다.")
            print("  무료 등급(F0)은 문서의 처음 2쪽만 처리한다. S0 리소스를 쓰거나 --pages로 나눠 넣을 것.")
            return 1
        if want is None:
            print(f"경고: 원본 쪽수를 확인하지 못했다(PyMuPDF 없음 또는 --pages 해석 불가). 처리된 쪽수 {done_pages}를 직접 대조할 것.")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    if opts["json"]:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)

    n_words, mean, low, handwritten = confidence_report(result)
    print(f"변환 완료! {done_pages}쪽, {len(content)}글자가 저장되었습니다. "
          f"(표 {len(result.get('tables') or [])}개, 그림 {len(result.get('figures') or [])}개)")
    if mean is not None:
        print(f"단어 confidence: {n_words}개 평균 {mean:.3f}, {LOW_CONFIDENCE} 미만 {len(low)}개")
        for page_no, text, c in low[:15]:
            print(f"  - p.{page_no} \"{text}\" ({c:.2f})")
        if len(low) > 15:
            print(f"  … 외 {len(low) - 15}개 (--json으로 전체 확인)")
    if handwritten:
        print(f"손글씨로 판정된 구간 {handwritten}곳이 있다(styles[].isHandwritten).")
    print(f"출력 파일: {out_path}")
    if opts["json"]:
        print(f"응답 JSON: {json_path}")
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
