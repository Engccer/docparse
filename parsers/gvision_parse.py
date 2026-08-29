# -*- coding: utf-8 -*-
"""
Google Cloud Vision DOCUMENT_TEXT_DETECTION 파서 (docparse).

용도: 수기 손글씨 답안 등 '오기 보존(diplomatic transcription)이 critical'한 문서에서,
LLM 파서의 자동교정·인명환각 없이 literal하게 추출하고, **단어별 confidence**를 함께 내보낸다.
저신뢰(conf<임계) 단어가 시각 판독 표적을 자동 생성한다(2026-06-14 PoC로 calibration 실증).

출력: <base>_gvision.md: 페이지별 clean text + "저신뢰: word(0.NN), ..." 라인.
  · clean text는 LlamaParse v2 출력과의 diff(③)에 사용 → 발산 토큰 = 환각/교정 후보
  · 저신뢰 목록은 육안 판독(④) 표적

실패 계약(2026-08-31): 페이지 호출이 429·5xx면 지수 백오프로 최대 2회 재시도(총 3회 호출)하고,
그래도 실패한 페이지가 하나라도 있으면 **출력 파일을 만들지 않고 종료 코드 1**
(종전에는 오류 제목만 남긴 채 완료 처리돼 그 쪽의 보정 초안도 만들어지지 않았다).
HTTP 200 안의 페이지별 `error` 필드도 실패로 본다. 실행 시작 시 같은 이름의 이전
출력을 지운다.

인증(둘 중 하나):
  1) API 키(권장·안정): export GOOGLE_VISION_API_KEY="..."   (Vision API 활성화된 프로젝트의 키)
  2) gcloud 액세스 토큰(토큰 ~1h 만료):
       export GV_TOKEN="$(gcloud auth print-access-token)"
       export GV_PROJECT="<billing 연결 + Vision API 활성화된 projectId>"
  ※ Vision API 활성화: gcloud services enable vision.googleapis.com --project <projectId>

사용:
  python parsers/gvision_parse.py <파일.pdf|.png|.jpg> [--low 0.90] [--lang en,ko] [--dpi 200] [--raw]

PDF는 PyMuPDF(fitz)로 페이지를 렌더해 페이지별로 호출한다. 단일 이미지는 그대로 호출.
무료 한도 1,000p/월. 초과 시 ~$1.5/1,000p. 학생 PII 등 민감 문서는 클라우드 전송 정책 확인 후 사용.
"""
import os, sys, json, base64, time, urllib.request, urllib.error, traceback

LOW = 0.90
LANG = ["en", "ko"]
DPI = 200
SAVE_RAW = False
RETRY_MAX = 3
RETRY_STATUS = {429, 500, 502, 503, 504}

VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


def get_auth():
    """(headers, url_suffix) 반환. API 키 우선, 없으면 bearer 토큰."""
    key = os.environ.get("GOOGLE_VISION_API_KEY")
    if key:
        return {"Content-Type": "application/json"}, f"?key={key}"
    tok = os.environ.get("GV_TOKEN")
    proj = os.environ.get("GV_PROJECT")
    if tok and proj:
        return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                "X-Goog-User-Project": proj}, ""
    print("오류: 인증 정보가 없습니다. 둘 중 하나를 설정하세요.")
    print("  1) export GOOGLE_VISION_API_KEY=\"...\"")
    print("  2) export GV_TOKEN=\"$(gcloud auth print-access-token)\" && export GV_PROJECT=\"<projectId>\"")
    print("     (Vision API 활성화: gcloud services enable vision.googleapis.com)")
    return None, None


def annotate(img_bytes, headers, suffix):
    """페이지 1장 호출. 429·5xx는 백오프 재시도. 실패 시 RuntimeError."""
    body = json.dumps({"requests": [{
        "image": {"content": base64.b64encode(img_bytes).decode()},
        "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
        "imageContext": {"languageHints": LANG}}]}).encode()
    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        req = urllib.request.Request(VISION_URL + suffix, data=body, headers=headers)
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=120).read())["responses"][0]
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.read().decode(errors='replace')[:200]}"
            if e.code in RETRY_STATUS and attempt < RETRY_MAX:
                wait = 2 ** attempt
                print(f"  재시도 {attempt}/{RETRY_MAX - 1} ({last_err.split()[0]} {last_err.split()[1]}), {wait}초 대기")
                time.sleep(wait)
                continue
            raise RuntimeError(last_err)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = f"네트워크 오류 {e}"
            if attempt < RETRY_MAX:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(last_err)
        # HTTP 200이어도 응답 안에 페이지별 error가 올 수 있다
        if "error" in resp:
            raise RuntimeError(f"응답 error: {json.dumps(resp['error'], ensure_ascii=False)[:200]}")
        return resp
    raise RuntimeError(last_err or "알 수 없는 오류")


def low_conf_words(fta):
    out = []
    for page in fta.get("pages", []):
        for block in page.get("blocks", []):
            for para in block.get("paragraphs", []):
                for w in para.get("words", []):
                    conf = w.get("confidence", 1.0)
                    if conf < LOW:
                        txt = "".join(s["text"] for s in w.get("symbols", []))
                        out.append((txt, conf))
    return out


def render_pdf_pages(path):
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    mat = fitz.Matrix(DPI / 72, DPI / 72)
    for i in range(len(doc)):
        yield i + 1, doc.load_page(i).get_pixmap(matrix=mat).tobytes("png")
    doc.close()


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    args = sys.argv[1:]
    global LOW, LANG, DPI, SAVE_RAW
    path = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--low":
            LOW = float(args[i + 1]); i += 2
        elif a == "--lang":
            LANG = [x.strip() for x in args[i + 1].split(",")]; i += 2
        elif a == "--dpi":
            DPI = int(args[i + 1]); i += 2
        elif a == "--raw":
            SAVE_RAW = True; i += 1
        else:
            path = a; i += 1
    if not path:
        print("사용: python gvision_parse.py <파일.pdf|.png|.jpg> [--low 0.90] [--lang en,ko] [--dpi 200] [--raw]")
        return 1
    if not os.path.exists(path):
        print(f"오류: 파일 없음: {path}"); return 1

    headers, suffix = get_auth()
    if headers is None:
        return 1

    base = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.dirname(path)
    ext = os.path.splitext(path)[1].lower()
    raw_dir = os.path.join(out_dir or ".", "_work-docparse", f"gvision_{base}")
    if SAVE_RAW:
        os.makedirs(raw_dir, exist_ok=True)

    out_path = os.path.join(out_dir, f"{base}_gvision.md") if out_dir else f"{base}_gvision.md"
    if os.path.exists(out_path):
        os.remove(out_path)
        print(f"기존 출력 제거: {out_path}")

    if ext == ".pdf":
        pages = list(render_pdf_pages(path))
    else:
        pages = [(1, open(path, "rb").read())]

    parts = [f"# {base}: Google Vision DOCUMENT_TEXT_DETECTION",
             f"\n> 단어 confidence(0~1) 기준 저신뢰(<{LOW}) 단어를 페이지마다 별도 표기. "
             f"clean text는 LlamaParse v2와의 diff용, 저신뢰 목록은 시각 판독 표적용.\n"]
    total_low = 0
    failed = []  # (page, reason)
    for n, img in pages:
        try:
            resp = annotate(img, headers, suffix)
        except RuntimeError as e:
            print(f"p.{n} 실패: {e}")
            failed.append((n, str(e)))
            continue
        if SAVE_RAW:
            json.dump(resp, open(os.path.join(raw_dir, f"p{n:02d}.json"), "w", encoding="utf-8"),
                      ensure_ascii=False)
        fta = resp.get("fullTextAnnotation", {})
        text = fta.get("text", "").strip()
        low = low_conf_words(fta)
        total_low += len(low)
        parts.append(f"\n## p.{n}\n\n{text}\n")
        if low:
            parts.append("저신뢰: " + ", ".join(f"{t}({c:.2f})" for t, c in low) + "\n")

    if failed:
        print(f"오류: {len(pages)}페이지 중 {len(failed)}페이지 호출 실패. 출력 파일을 만들지 않았습니다.")
        for n, reason in failed:
            print(f"  - p.{n}: {reason[:120]}")
        print("→ 한도(429)면 잠시 후 재실행, 인증(401/403)이면 GV_TOKEN 갱신·Vision API 활성화 확인.")
        return 1

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    print(f"변환 완료! {len(pages)}페이지, 저신뢰 단어 총 {total_low}개")
    print(f"출력 파일: {out_path}")
    return 0


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except Exception as e:
        print(f"\n오류 발생: {e}")
        traceback.print_exc()
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nEnter를 눌러 종료...")
        except EOFError:
            pass
    sys.exit(exit_code)
