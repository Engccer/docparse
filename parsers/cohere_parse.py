# -*- coding: utf-8 -*-
"""
Cohere Parse 파서 (docparse).

  python parsers/cohere_parse.py <파일.pdf|.png|.jpg|.gif|.webp> [--dpi 200] [--model parse-v5.0]
    → <파일>_cohere.md

모델: parse-v5.0 (2.3B VLM, 8,192 토큰 컨텍스트). 마크다운 + HTML 표 + 이미지 설명을 낸다.
한국어가 9개 안정 지원 언어에 포함된다(아랍어·영어·프랑스어·독일어·일본어·한국어·이탈리아어·
포르투갈어·스페인어). 요금 $1.50/1,000쪽. 트라이얼 키는 월 1,000콜 무료.

⚠️ 엔드포인트가 **이미지만** 받는다(`document.type = image_url`). PDF 직접 입력은 지원되지
않으므로 PyMuPDF로 페이지를 렌더해 **쪽당 1회씩** 호출한다(gvision_parse.py와 같은 경유 구조).
따라서 쪽수 = 호출 수 = 과금 단위다.

실패 계약: 페이지 호출이 429·5xx면 지수 백오프로 최대 2회 재시도(총 3회 호출)하고, 그래도
실패한 페이지가 하나라도 있으면 **출력 파일을 만들지 않고 종료 코드 1**(일부 쪽이 빠진 파일을
완료본으로 남기지 않는다). 모든 쪽이 비어도 같다. 실행 시작 시 같은 이름의 이전 출력을 지운다.

API 키: export COHERE_API_KEY="..."   (https://dashboard.cohere.com/api-keys)
"""
import os
import sys
import json
import base64
import time
import urllib.request
import urllib.error
import traceback

API_URL = "https://api.cohere.com/v2/parse"
MODEL = "parse-v5.0"
DPI = 200
RETRY_MAX = 3
RETRY_STATUS = {429, 500, 502, 503, 504}

# Parse 입력 제한: 20MB / 50메가픽셀. 여유를 두고 자체 상한을 잡는다.
MAX_PIXELS = 45_000_000
MAX_BYTES = 18 * 1024 * 1024
# 페이지당 출력이 컨텍스트(8,192) 상한에 닿으면 잘렸을 수 있다.
TOKEN_WARN = 8_000

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
SUPPORTED_EXT = set(IMAGE_MIME) | {".pdf"}


def parse_page(img_bytes, mime, api_key, model):
    """페이지 1장 호출 → 응답 dict. 429·5xx는 백오프 재시도. 실패 시 RuntimeError."""
    data_uri = f"data:{mime};base64," + base64.b64encode(img_bytes).decode()
    body = json.dumps({
        "model": model,
        "document": {"type": "image_url", "image_url": data_uri},
        "output_format": "markdown",
    }).encode()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Client-Name": "docparse",
    }
    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        req = urllib.request.Request(API_URL, data=body, headers=headers)
        try:
            return json.loads(urllib.request.urlopen(req, timeout=180).read())
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.read().decode(errors='replace')[:200]}"
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


def page_markdown(resp):
    """응답에서 (마크다운 본문, 이미지 설명 목록, 출력 토큰 수) 추출.

    응답 스키마: {"pages": [{"type": "markdown", "index": 0,
                            "markdown": {"content": "...", "images": [...]}}], "meta": {...}}
    한 장을 보냈으므로 pages는 1개가 정상이지만, 여러 개면 순서대로 잇는다.
    """
    bodies, images = [], []
    for page in resp.get("pages") or []:
        md = page.get("markdown") or {}
        bodies.append((md.get("content") or "").strip())
        for img in md.get("images") or []:
            desc = (img.get("description") or "").strip()
            if desc:
                images.append((img.get("id") or "image", img.get("category") or "other", desc))
    meta = resp.get("meta") or {}
    tokens = None
    for holder in (meta.get("tokens"), meta.get("billed_units")):
        if isinstance(holder, dict) and holder.get("output_tokens") is not None:
            tokens = holder["output_tokens"]
            break
    return "\n\n".join(b for b in bodies if b), images, tokens


def render_pdf_pages(path, dpi):
    """PDF 페이지를 PNG로 렌더. 입력 상한(50MP·20MB)을 넘으면 배율을 낮춰 재렌더."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    doc = fitz.open(path)
    try:
        for i in range(len(doc)):
            page = doc.load_page(i)
            zoom = dpi / 72
            while True:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                png = pix.tobytes("png")
                if (pix.width * pix.height <= MAX_PIXELS and len(png) <= MAX_BYTES) or zoom <= 0.5:
                    break
                zoom *= 0.75
                print(f"  p.{i + 1}: 입력 상한 초과 → 배율 {zoom:.2f}로 재렌더")
            yield i + 1, png
    finally:
        doc.close()


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    args = sys.argv[1:]
    dpi, model, path = DPI, MODEL, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--dpi":
            dpi = int(args[i + 1]); i += 2
        elif a == "--model":
            model = args[i + 1]; i += 2
        else:
            path = a; i += 1

    if not path:
        print("사용: python cohere_parse.py <파일.pdf|.png|.jpg|.gif|.webp> [--dpi 200] [--model parse-v5.0]")
        print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXT))}")
        return 1
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXT:
        print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
        print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXT))}")
        print("  (Parse 엔드포인트는 이미지만 받는다. HWPX·DOCX·XLSX·PPTX는 다른 파서를 쓸 것)")
        return 1
    if not os.path.exists(path):
        print(f"오류: 파일을 찾을 수 없습니다: {path}")
        return 1

    api_key = os.environ.get("COHERE_API_KEY")
    if not api_key:
        print("오류: COHERE_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export COHERE_API_KEY=\"your-api-key\"  (Windows: setx COHERE_API_KEY \"your-api-key\")")
        print("키 발급: https://dashboard.cohere.com/api-keys  (트라이얼 키는 월 1,000콜 무료)")
        return 1

    base = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.dirname(path)
    out_path = os.path.join(out_dir, f"{base}_cohere.md") if out_dir else f"{base}_cohere.md"
    if os.path.exists(out_path):
        os.remove(out_path)
        print(f"기존 출력 제거: {out_path}")

    print(f"입력 파일: {path}")
    if ext == ".pdf":
        try:
            pages = list(render_pdf_pages(path, dpi))
        except ImportError:
            print("오류: PyMuPDF를 찾을 수 없습니다. PDF는 페이지를 이미지로 렌더해야 호출할 수 있습니다.")
            print("설치 명령: pip install PyMuPDF")
            return 1
        mime = "image/png"
    else:
        with open(path, "rb") as f:
            pages = [(1, f.read())]
        mime = IMAGE_MIME[ext]

    total = len(pages)
    if total == 0:
        print("오류: 페이지가 없습니다.")
        return 1
    print(f"변환 중... {total}쪽 = API 호출 {total}회 (쪽당 과금)")

    parts, empty_pages, truncated, failed = [], [], [], []
    for n, img in pages:
        try:
            resp = parse_page(img, mime, api_key, model)
        except RuntimeError as e:
            print(f"p.{n} 실패: {e}")
            failed.append((n, str(e)))
            continue
        body, images, tokens = page_markdown(resp)
        if not body:
            empty_pages.append(n)
        if tokens is not None and tokens >= TOKEN_WARN:
            truncated.append((n, tokens))
        chunk = [f"<!-- Page {n}/{total} -->", "", body]
        if images:
            chunk.append("")
            chunk.extend(f"<!-- 이미지 {iid} ({cat}): {desc} -->" for iid, cat, desc in images)
        parts.append("\n".join(chunk))

    if failed:
        print(f"오류: {total}쪽 중 {len(failed)}쪽 호출 실패. 출력 파일을 만들지 않았습니다.")
        for n, reason in failed:
            print(f"  - p.{n}: {reason[:120]}")
        print("→ 한도(429)면 잠시 후 재실행, 인증(401/403)이면 COHERE_API_KEY 확인.")
        return 1
    if len(empty_pages) == total:
        print("오류: 모든 페이지의 결과가 비어 있습니다. 출력 파일을 만들지 않았습니다.")
        return 1

    content = "\n\n---\n\n".join(parts)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"변환 완료! {total}페이지, {len(content)}글자가 저장되었습니다.")
    if empty_pages:
        shown = ", ".join(str(p) for p in empty_pages[:20])
        print(f"경고: 내용이 빈 페이지 {len(empty_pages)}쪽: {shown}{' ...' if len(empty_pages) > 20 else ''}")
        print("  (백지·그림 전용 쪽이면 정상. 본문이 있는 쪽이면 다른 파서로 그 쪽을 보완할 것)")
    if truncated:
        shown = ", ".join(f"p.{n}({t}토큰)" for n, t in truncated[:20])
        print(f"경고: 컨텍스트 상한(8,192)에 근접한 페이지 {len(truncated)}쪽: {shown}")
        print("  (조밀한 쪽에서 뒷부분이 잘렸을 수 있다. 해당 쪽은 다른 파서와 대조할 것)")
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
