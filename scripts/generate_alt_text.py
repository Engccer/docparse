"""LlamaParse v2 출력의 이미지 placeholder를 시각장애인 접근성에 적합한
한국어 상세 alt text로 변환.

워크플로우
1. LlamaParse v2 출력 .md에서 ![alt](page_N_image_M_v2.jpg) 패턴을 페이지별로 추출
2. PyMuPDF로 이미지가 있는 페이지를 PNG로 렌더링
3. Gemini Vision API에 페이지 이미지 + 영문 alt 목록을 보내 페이지 단위로 한국어 상세 alt 생성
4. 결과를 매핑 JSON으로 저장하고, .md의 placeholder를 (이미지: 한국어 alt) 형태로 치환

사용 예시
  python generate_alt_text.py --pdf doc.pdf --markdown doc_llamaparse.md \\
      --output doc_with_alt.md --map alt_map.json

  # 이미 만든 매핑 JSON 재사용 (Gemini 호출 생략)
  python generate_alt_text.py --markdown doc_llamaparse.md \\
      --reuse-map alt_map.json --output doc_with_alt.md

환경 변수
  GEMINI_API_KEY 필수 (--reuse-map만 사용 시는 불필요)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Windows PowerShell의 기본 cp949 stdout이 한국어 한자·이모지를 인코딩하지 못해
# 첫 print에서 UnicodeEncodeError가 나면 진행이 멈춘 것처럼 보임. UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

LLAMA_IMG_PATTERN = re.compile(
    # LlamaParse v2가 출력하는 두 가지 placeholder 패턴 모두 매칭
    #   1. 일반: page_N_image_M_v2.jpg                 (대부분)
    #   2. layout OCR: page_N_layout_ocr_<hash>_..png  (페이지 디자인 요소를 잡은 경우)
    r"!\[([^\]]*)\]\(page_(\d+)_(?:image_(\d+)_v2\.jpg|layout_\w+\.\w+)\)"
)

DEFAULT_PROMPT_TEMPLATE = """이 PDF 페이지에 포함된 시각 자료에 대해, 시각장애인이 스크린리더로 들었을 때 시각 정보의 핵심을 정확히 이해할 수 있도록 한국어 alt text를 작성하세요.

[페이지에서 식별된 시각 자료 영문/한국어 설명 목록]
{alt_list}

[작성 지침]
- 각 항목을 1~3문장으로 한국어 alt text로 작성.
- 같은 종류의 시각 자료(일러스트, 다이어그램, 로고, 사진)가 여러 개면 페이지 안 위치(좌상/우하 등)·색·구성으로 구분.
- 문서 맥락에 맞게 표현. 단순 장식은 짧게, 정보가 담긴 다이어그램·표는 핵심 내용까지 자세히.
- 결과는 반드시 JSON 배열로만 출력(다른 설명 없이):
[
  {{"index": 1, "alt": "한국어 alt text 1"}},
  {{"index": 2, "alt": "한국어 alt text 2"}}
]
- index는 입력 목록의 순번(1부터)을 그대로 사용."""


def is_likely_korean(text: str) -> bool:
    """문자열에 한글이 절반 이상이면 True."""
    if not text:
        return False
    hangul = sum(0xAC00 <= ord(c) <= 0xD7A3 for c in text)
    return hangul * 2 >= len(text.strip())


def extract_images(markdown_text: str, skip_korean: bool = False):
    """페이지별 이미지 placeholder 목록을 반환.

    Returns: {page_num: [(image_idx, alt, full_match), ...]}
    """
    by_page: dict[int, list[tuple[int, str, str]]] = {}
    layout_seq: dict[int, int] = {}  # layout 패턴은 image_idx가 없어 페이지 내 순서로 부여
    for m in LLAMA_IMG_PATTERN.finditer(markdown_text):
        alt = m.group(1)
        page = int(m.group(2))
        idx_str = m.group(3)
        if idx_str is not None:
            idx = int(idx_str)
        else:
            layout_seq[page] = layout_seq.get(page, 999) + 1
            idx = layout_seq[page]
        if skip_korean and is_likely_korean(alt):
            continue
        by_page.setdefault(page, []).append((idx, alt, m.group(0)))
    for k in by_page:
        by_page[k].sort(key=lambda x: x[0])
    return by_page


def render_page(doc, page_num: int, dpi: int) -> bytes:
    page = doc[page_num - 1]
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png")


def call_gemini(client, model: str, png_bytes: bytes, alt_list_str: str,
                prompt_template: str, types_mod):
    prompt = prompt_template.format(alt_list=alt_list_str)
    response = client.models.generate_content(
        model=model,
        contents=[
            types_mod.Part.from_bytes(data=png_bytes, mime_type="image/png"),
            prompt,
        ],
    )
    body = (response.text or "").strip()
    m = re.search(r"\[.*\]", body, re.DOTALL)
    if not m:
        raise RuntimeError(f"Gemini 응답에서 JSON 배열을 찾지 못함. body[:200]={body[:200]}")
    return json.loads(m.group(0))


def generate_map(pdf_path: Path, by_page, model: str, dpi: int,
                 prompt_template: str, sleep_sec: float = 0.5) -> dict:
    """페이지별 Gemini 호출로 매핑 dict 생성."""
    try:
        import fitz
        from google import genai
        from google.genai import types as types_mod
    except ImportError as e:
        sys.exit(f"필수 패키지 누락: {e}\n설치: pip install pymupdf google-genai")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
    client = genai.Client(api_key=api_key)
    doc = fitz.open(str(pdf_path))
    try:
        result_map: dict[str, dict] = {}
        for page_num in sorted(by_page.keys()):
            items = by_page[page_num]
            alt_list_str = "\n".join(
                f"{i+1}. {alt}" for i, (_, alt, _) in enumerate(items)
            )
            print(f"[페이지 {page_num}] 이미지 {len(items)}개 alt 생성 중...", flush=True)
            try:
                png = render_page(doc, page_num, dpi)
                parsed = call_gemini(client, model, png, alt_list_str,
                                     prompt_template, types_mod)
            except Exception as e:
                print(f"  [오류] {e}", flush=True)
                continue
            for item in parsed:
                i = item.get("index")
                ko_alt = (item.get("alt") or "").strip()
                if i is None or not ko_alt or i - 1 >= len(items):
                    continue
                orig_idx, en_alt, full_md = items[i - 1]
                result_map[full_md] = {
                    "page": page_num,
                    "image_index": orig_idx,
                    "en_alt": en_alt,
                    "ko_alt": ko_alt,
                }
            print(f"  완료 ({len(parsed)}개)", flush=True)
            time.sleep(sleep_sec)
    finally:
        doc.close()
    return result_map


def inject(markdown_text: str, alt_map: dict, keep_unmapped_alt: bool = True) -> tuple[str, int, int]:
    """매핑 dict로 markdown placeholder를 치환.

    Returns: (새 텍스트, 치환된 개수, 매핑 없는 개수)
    """
    replaced = 0
    unmapped = 0

    def _replace(m: re.Match) -> str:
        nonlocal replaced, unmapped
        full = m.group(0)
        entry = alt_map.get(full)
        if entry:
            replaced += 1
            return f"(이미지: {entry['ko_alt']})"
        unmapped += 1
        if keep_unmapped_alt:
            alt = m.group(1).strip()
            return f"(이미지: {alt})" if alt else ""
        return ""

    new_text = LLAMA_IMG_PATTERN.sub(_replace, markdown_text)
    return new_text, replaced, unmapped


def main():
    parser = argparse.ArgumentParser(
        description="LlamaParse v2 이미지 placeholder를 한국어 상세 alt text로 치환",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--markdown", required=True, type=Path,
                        help="LlamaParse v2 출력 .md (이미지 placeholder 포함)")
    parser.add_argument("--pdf", type=Path,
                        help="원본 PDF (페이지 렌더링용). --reuse-map 사용 시 생략 가능")
    parser.add_argument("--output", type=Path,
                        help="alt 치환된 .md 출력 경로. 미지정 시 stdout")
    parser.add_argument("--map", type=Path,
                        help="생성된 매핑 JSON 저장 경로 (재사용용)")
    parser.add_argument("--reuse-map", type=Path,
                        help="기존 매핑 JSON 재사용 (Gemini 호출 생략)")
    parser.add_argument("--skip-korean", action="store_true",
                        help="이미 한국어인 alt는 건너뛰고 영문 alt만 재생성")
    parser.add_argument("--dpi", type=int, default=120,
                        help="페이지 렌더링 DPI (기본 120)")
    parser.add_argument("--model", default="gemini-flash-latest",
                        help="Gemini 모델 (기본 gemini-flash-latest, 서버측 stable flash 자동 추적)")
    parser.add_argument("--prompt", type=Path,
                        help="custom 프롬프트 템플릿 파일. {alt_list} 자리표시자 포함")
    args = parser.parse_args()

    if not args.markdown.exists():
        sys.exit(f"markdown 파일 없음: {args.markdown}")
    markdown_text = args.markdown.read_text(encoding="utf-8")

    if args.reuse_map:
        if not args.reuse_map.exists():
            sys.exit(f"reuse-map 파일 없음: {args.reuse_map}")
        alt_map = json.loads(args.reuse_map.read_text(encoding="utf-8"))
        print(f"매핑 JSON 재사용: {len(alt_map)}개 항목", flush=True)
    else:
        if not args.pdf or not args.pdf.exists():
            sys.exit("--reuse-map 미지정 시 --pdf 필수")
        by_page = extract_images(markdown_text, skip_korean=args.skip_korean)
        total = sum(len(v) for v in by_page.values())
        print(f"이미지 {total}개 (페이지 {len(by_page)}개)에 대해 alt 생성", flush=True)
        if total == 0:
            print("이미지 없음. 종료.", flush=True)
            return
        prompt_template = (
            args.prompt.read_text(encoding="utf-8") if args.prompt
            else DEFAULT_PROMPT_TEMPLATE
        )
        alt_map = generate_map(args.pdf, by_page, args.model, args.dpi, prompt_template)
        if args.map:
            args.map.write_text(json.dumps(alt_map, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            print(f"매핑 JSON 저장: {args.map}", flush=True)

    new_text, replaced, unmapped = inject(markdown_text, alt_map)
    print(f"치환 완료: {replaced}개 매핑 적용, {unmapped}개 영문 alt fallback", flush=True)

    if args.output:
        args.output.write_text(new_text, encoding="utf-8")
        print(f"출력: {args.output}", flush=True)
    else:
        sys.stdout.write(new_text)


if __name__ == "__main__":
    main()
