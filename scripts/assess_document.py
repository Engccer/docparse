"""문서 사전 진단: 페이지 수, 텍스트 레이어, 표 힌트, 티어 분류.

Usage:
    python assess_document.py "<파일경로>"

Output (stdout, JSON):
    {
        "file": "document.pdf",
        "format": "pdf",
        "pages": 187,
        "has_text_layer": true,
        "table_hint": false,
        "tier": "xlarge",
        "recommended_parsers": ["opendataloader", "upstage"]
    }
"""

import json
import os
import sys


SUPPORTED_FORMATS = {
    ".pdf": "pdf",
    ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".hwp": "hwp", ".hwpx": "hwpx",
    ".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx",
}


def assess_pdf(file_path):
    """PDF 파일 진단 (PyMuPDF 사용)."""
    try:
        import fitz
    except ImportError:
        print("오류: PyMuPDF 패키지가 필요합니다. pip install pymupdf", file=sys.stderr)
        return None

    doc = fitz.open(file_path)
    pages = len(doc)

    # 텍스트 레이어 확인 (첫 3페이지 샘플링)
    text_chars = 0
    sample_pages = min(3, pages)
    for i in range(sample_pages):
        text_chars += len(doc[i].get_text().strip())
    has_text_layer = text_chars > (50 * sample_pages)

    # 표 힌트 (탭, 파이프 문자 기반 휴리스틱)
    table_pages = 0
    check_pages = min(10, pages)
    for i in range(check_pages):
        text = doc[i].get_text()
        if "|" in text or text.count("\t") > 3:
            table_pages += 1
    table_hint = table_pages >= (check_pages * 0.3)

    doc.close()

    # 티어 분류
    if pages <= 15:
        tier = "small"
    elif pages <= 60:
        tier = "medium"
    elif pages <= 100:
        tier = "large"
    else:
        tier = "xlarge"

    # 보정: 텍스트 레이어 없으면 한 단계 올림
    if not has_text_layer:
        tier_order = ["small", "medium", "large", "xlarge"]
        idx = tier_order.index(tier)
        if idx < len(tier_order) - 1:
            tier = tier_order[idx + 1]

    return {
        "pages": pages,
        "has_text_layer": has_text_layer,
        "table_hint": table_hint,
        "tier": tier,
    }


def recommend_parsers(fmt, tier, has_text_layer, table_hint, lang="ko"):
    """티어와 포맷에 따른 파서 추천."""

    if fmt == "pdf":
        if tier == "small":
            parsers = ["gemini"]
        elif tier == "medium":
            parsers = ["upstage", "gemini"]
        elif tier == "large":
            parsers = ["opendataloader", "upstage"]
        else:  # xlarge
            parsers = ["opendataloader", "upstage"]

        # 보정 규칙
        if not has_text_layer and "upstage" not in parsers:
            parsers.append("upstage")
        if lang != "ko":
            parsers.append("mistral")

    elif fmt == "hwpx":
        # 무료·오프라인 로컬 파서 우선. 이미지 내 텍스트·레이아웃·recall/마커 경고
        # 시에만 Upstage로 교차/대체(SKILL.md HWPX 티어 참조). 미설치 시 Upstage 폴백.
        parsers = ["hwpx_local"]
    elif fmt == "hwp":
        # HWP(구형 바이너리)는 hwpx_local이 직접 못 읽는다. hwpx-automation의
        # hwp2hwpx로 HWPX 변환 후 hwpx_local 권장. 변환 없이 직접 처리는 Upstage.
        parsers = ["upstage"]
    elif fmt in ("docx", "pptx"):
        parsers = ["upstage", "llamaparse"]
    elif fmt == "xlsx":
        parsers = ["upstage", "llamaparse"]
    elif fmt == "image":
        parsers = ["upstage", "gemini"]
    else:
        parsers = ["upstage"]

    return parsers


def main():
    if len(sys.argv) < 2:
        print("사용법: python assess_document.py <파일경로> [--lang ko]")
        return

    # 인수 파싱
    args = sys.argv[1:]
    lang = "ko"
    file_path = None
    i = 0
    while i < len(args):
        if args[i] == "--lang" and i + 1 < len(args):
            lang = args[i + 1]
            i += 2
        elif file_path is None:
            file_path = args[i]
            i += 1
        else:
            i += 1

    if not file_path or not os.path.exists(file_path):
        print(f"오류: 파일을 찾을 수 없습니다: {file_path}", file=sys.stderr)
        return

    ext = os.path.splitext(file_path)[1].lower()
    fmt = SUPPORTED_FORMATS.get(ext)
    if not fmt:
        print(f"오류: 지원하지 않는 파일 형식입니다: {ext}", file=sys.stderr)
        print(f"지원 형식: {', '.join(SUPPORTED_FORMATS.keys())}", file=sys.stderr)
        return

    result = {
        "file": os.path.basename(file_path),
        "format": fmt,
    }

    if fmt == "pdf":
        pdf_info = assess_pdf(file_path)
        if pdf_info is None:
            return
        result.update(pdf_info)
    else:
        # 비PDF: 페이지 개념 없음, 파일 크기 기반 간이 판단
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        result["size_mb"] = round(size_mb, 1)
        result["pages"] = None
        result["has_text_layer"] = True  # 비PDF는 텍스트 기반
        result["table_hint"] = fmt == "xlsx"
        if fmt == "hwpx":
            result["tier"] = "hwpx"  # 로컬 hwpx_local 우선 + Upstage 폴백
        elif fmt == "hwp":
            result["tier"] = "hwpx"  # HWPX 변환 후 hwpx 티어로 처리(직접은 Upstage)
        elif size_mb < 5:
            result["tier"] = "small"
        else:
            result["tier"] = "medium"

    parsers = recommend_parsers(
        fmt,
        result["tier"],
        result.get("has_text_layer", True),
        result.get("table_hint", False),
        lang,
    )
    result["recommended_parsers"] = parsers
    result["lang"] = lang

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
