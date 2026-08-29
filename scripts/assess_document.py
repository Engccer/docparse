"""문서 사전 진단: 페이지 수, 텍스트 레이어, 표 힌트, 티어 분류, 보정 규칙 신호.

Usage:
    python assess_document.py "<파일경로>" [--lang ko]

Output (stdout, JSON):
    {
        "file": "document.pdf",
        "format": "pdf",
        "pages": 187,
        "has_text_layer": true,
        "table_hint": false,
        "tier": "xlarge",
        "recommended_parsers": ["llamaparse", "opendataloader"],
        "lang": "ko",
        "signals": {
            "sampled_pages": [1, 2, 3, 20, 40, ...],
            "text_pages": 12,            # 표본 중 50자 이상 텍스트가 있는 쪽 수
            "pua_per_10k": 3.1,          # 텍스트 레이어 1만 자당 PUA(U+E000~F8FF) 코드포인트
            "latin_ratio": 0.12          # 문자(한글+라틴) 중 라틴 비율
        },
        "rule_hints": ["..."]            # references/tier-rules.md 절 이름. 진단으로 걸린 것만
    }

추천 표는 SKILL.md Step 2 기본 티어 표와 tier-rules.md 「텍스트 레이어 없음」 절을
그대로 옮긴 것이다(2026-08-31 정정. 종전에는 medium=Upstage+Gemini, large=ODL+Upstage로
정본과 반대였고 스캔 문서에도 ODL을 추천했다). 정본이 바뀌면 이 표도 함께 바꾼다.

임계값 출처(새로 지어내지 않았다. 표본 근거가 약한 것은 그대로 적는다):
- 텍스트 레이어 쪽 판정 50자/쪽: 관행값. 표본 근거 없음.
- table_hint 30%: 관행값. 표본 근거 없음(격자 검출 자체는 합성 PDF 양성 3·음성 4로 검증, CHANGELOG 3.19).
- pua_per_10k 100: tier-rules 「수식이 있는 시험지」 절(78쪽 수식 시험지 1건 114~212 vs 비수식 3건 0.3~8.2).
- latin_ratio 0.5: tier-rules 「Mistral Primary 고려 조건」의 "영어 비율 50%"(근거 미표기).
"""

import json
import os
import re
import sys


SUPPORTED_FORMATS = {
    ".pdf": "pdf",
    ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".hwp": "hwp", ".hwpx": "hwpx",
    ".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx",
}

TEXT_PAGE_MIN_CHARS = 50
TABLE_HINT_RATIO = 0.3
PUA_PER_10K_THRESHOLD = 100.0
LATIN_RATIO_THRESHOLD = 0.5
SAMPLE_MAX = 12

_PUA = re.compile("[-]")
_HANGUL = re.compile("[가-힣]")
_LATIN = re.compile("[A-Za-zÀ-ÿ]")


def page_has_ruled_grid(page, min_lines=3, tol=1.0):
    """벡터 괘선 격자 판정: 서로 교차하는 수평선·수직선이 각 min_lines개 이상.

    괘선은 벡터 그래픽이지 문자가 아니므로 텍스트 기반 휴리스틱(파이프·탭)으로는
    잡히지 않는다. get_drawings()의 선분("l")과 사각형("re" 4변 분해)을 모아
    같은 위치(1pt 반올림)의 구간을 겹치거나 tol 이내로 맞닿을 때만 병합하고
    (간격은 보존 — 나란히 정렬된 분리 상자들을 하나의 긴 선으로 오판하지 않음),
    교차 수를 센다. 격자라면 각 선이 반대 방향 선 min_lines개 이상과 교차한다.
    상자 하나의 변은 반대 방향 선 2개(자기 모서리)와만 교차해 미달이고, tol을
    1pt로 좁혀 이중 테두리의 평행 근접선(통상 2pt 간격)도 교차로 세지 않는다.
    """
    h_raw = {}  # round(y) -> [[x0, x1], ...]
    v_raw = {}  # round(x) -> [[y0, y1], ...]

    def add(store, pos, lo, hi):
        if hi - lo < 8:
            return
        store.setdefault(round(pos), []).append([lo, hi])

    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) <= 1:
                    add(h_raw, (p1.y + p2.y) / 2, min(p1.x, p2.x), max(p1.x, p2.x))
                elif abs(p1.x - p2.x) <= 1:
                    add(v_raw, (p1.x + p2.x) / 2, min(p1.y, p2.y), max(p1.y, p2.y))
            elif item[0] == "re":
                r = item[1]
                add(h_raw, r.y0, r.x0, r.x1)
                add(h_raw, r.y1, r.x0, r.x1)
                add(v_raw, r.x0, r.y0, r.y1)
                add(v_raw, r.x1, r.y0, r.y1)

    def merged_lines(store):
        """같은 위치의 구간을 인접(≤tol)할 때만 병합해 (위치, [lo, hi]) 목록으로."""
        lines = []
        for pos, spans in store.items():
            spans.sort()
            out = [spans[0][:]]
            for lo, hi in spans[1:]:
                if lo <= out[-1][1] + tol:
                    out[-1][1] = max(out[-1][1], hi)
                else:
                    out.append([lo, hi])
            lines.extend((pos, span) for span in out)
        return lines

    h_lines = merged_lines(h_raw)
    v_lines = merged_lines(v_raw)
    if len(h_lines) < min_lines or len(v_lines) < min_lines:
        return False

    def crossings(pos, span, others):
        return sum(
            1 for other_pos, (lo, hi) in others
            if span[0] - tol <= other_pos <= span[1] + tol and lo - tol <= pos <= hi + tol
        )

    grid_h = sum(1 for y, span in h_lines if crossings(y, span, v_lines) >= min_lines)
    if grid_h < min_lines:
        return False
    grid_v = sum(1 for x, span in v_lines if crossings(x, span, h_lines) >= min_lines)
    return grid_v >= min_lines


def sample_page_indexes(pages, limit=SAMPLE_MAX):
    """앞 3쪽 + 문서 전체에 고르게 퍼진 쪽(0-based, 중복 제거·정렬).

    앞쪽만 보면 표지가 통이미지인 보고서가 스캔본으로 오판된다(gotchas.md 실측).
    """
    if pages <= limit:
        return list(range(pages))
    idx = {0, 1, 2}
    rest = limit - len(idx)
    for k in range(rest):
        idx.add(round(3 + (pages - 4) * (k + 1) / (rest + 1)))
    return sorted(i for i in idx if i < pages)


def assess_pdf(file_path):
    """PDF 파일 진단 (PyMuPDF 사용)."""
    # `import fitz`는 PyMuPDF 1.28+에서 폐기 경고를 **stdout**에 찍어 JSON 앞에 섞인다.
    # 신 모듈명(pymupdf)을 먼저 쓰고, 구버전에서만 fitz로 떨어진다.
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            print("오류: PyMuPDF 패키지가 필요합니다. pip install pymupdf", file=sys.stderr)
            return None

    doc = fitz.open(file_path)
    pages = len(doc)
    sampled = sample_page_indexes(pages)

    # 텍스트 레이어: 표본 쪽마다 글자 수를 세고, 과반이 50자 이상이면 true.
    text_pages = 0
    text_all = []
    for i in sampled:
        t = doc[i].get_text()
        text_all.append(t)
        if len(t.strip()) >= TEXT_PAGE_MIN_CHARS:
            text_pages += 1
    has_text_layer = text_pages * 2 >= len(sampled) if sampled else False

    # 표 힌트: 벡터 괘선 격자 기반. 구 휴리스틱(파이프·탭 문자)은 선으로 그린
    # 표를 원천적으로 못 잡아 교체(2026-08-10, CHANGELOG 3.19).
    grid_pages = sum(1 for i in sampled[:10] if page_has_ruled_grid(doc[i]))
    table_hint = grid_pages >= (min(10, len(sampled)) * TABLE_HINT_RATIO)

    doc.close()

    joined = "".join(text_all)
    pua_cp = len(_PUA.findall(joined))
    pua_per_10k = round(pua_cp * 10000 / len(joined), 1) if joined else 0.0
    hangul = len(_HANGUL.findall(joined))
    latin = len(_LATIN.findall(joined))
    latin_ratio = round(latin / (hangul + latin), 2) if (hangul + latin) else 0.0

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
        "signals": {
            "sampled_pages": [i + 1 for i in sampled],
            "text_pages": text_pages,
            "pua_per_10k": pua_per_10k,
            "latin_ratio": latin_ratio,
        },
    }


def recommend_parsers(fmt, tier, has_text_layer, table_hint, lang="ko"):
    """티어와 포맷에 따른 파서 추천. SKILL.md 기본 티어 표 + tier-rules 스캔 절을 그대로 옮긴다."""

    if fmt == "pdf":
        if tier == "small":
            parsers = ["gemini"]
        elif tier == "medium":
            parsers = ["llamaparse", "upstage"]
        else:  # large, xlarge
            parsers = ["llamaparse", "opendataloader"]

        # 스캔(텍스트 레이어 없음): ODL은 텍스트 레이어 필수라 제외.
        # tier-rules 「텍스트 레이어 없음」: medium=v2+Upstage, large/xlarge=v2+Upstage+Mistral.
        if not has_text_layer:
            parsers = [p for p in parsers if p != "opendataloader"]
            if tier != "small" and "upstage" not in parsers:
                parsers.append("upstage")
            if tier in ("large", "xlarge") and "mistral" not in parsers:
                parsers.append("mistral")
        if lang != "ko" and "mistral" not in parsers:
            parsers.append("mistral")

        # Tier 0 (결정론 우선 게이트): 텍스트 레이어 + 벡터 괘선 격자면
        # pdfplumber(로컬·무료)를 선두에 둔다. 목표 산출물이 표 데이터인지는
        # 에이전트가 판단하고, 자가검증 실패 시 뒤의 티어 파서로 승격한다
        # (SKILL.md Step 2 Tier 0 절).
        if table_hint and has_text_layer:
            parsers.insert(0, "pdfplumber")

    elif fmt == "hwpx":
        # 무료·오프라인 로컬 파서 우선. 이미지 내 텍스트·레이아웃·recall/마커 경고
        # 시에만 Upstage로 교차/대체(SKILL.md HWPX 티어 참조). 미설치 시 Upstage 폴백.
        parsers = ["hwpx_local"]
    elif fmt == "hwp":
        # HWP(구형 바이너리)는 hwpx_local이 직접 못 읽는다. hwpx-automation의
        # hwp2hwpx로 HWPX 변환 후 hwpx_local 권장. 변환 없이 직접 처리는 Upstage.
        parsers = ["upstage"]
    elif fmt == "docx":
        # 로컬·무료 파서 우선. 거부(텍스트박스·각주·중첩 표·recall 불일치) 시
        # Upstage·LlamaParse로 승격(SKILL.md Office 로컬 티어 참조).
        parsers = ["docx_local", "upstage", "llamaparse"]
    elif fmt == "pptx":
        parsers = ["upstage", "llamaparse"]
    elif fmt == "xlsx":
        # 로컬·무료 파서 우선. 원시 XML 교차 검증 불일치·차트 텍스트 중요 시 승격.
        parsers = ["xlsx_local", "upstage", "llamaparse"]
    elif fmt == "image":
        parsers = ["upstage", "gemini"]
    else:
        parsers = ["upstage"]

    return parsers


def rule_hints(fmt, tier, has_text_layer, table_hint, signals, lang):
    """진단만으로 걸리는 tier-rules 절 이름. 걸리지 않은 절은 적지 않는다(해당 없음 ≠ 미판정).

    손글씨·합본·인구통계 교차표·병합셀처럼 진단으로 못 잡는 특성은 SKILL.md 보정 규칙
    목록에서 에이전트가 판단한다.
    """
    hints = []
    if fmt == "pdf":
        if table_hint and has_text_layer:
            hints.append("괘선 정형 표 PDF (Tier 0)")
        if not has_text_layer:
            hints.append("텍스트 레이어 없음 (스캔/이미지 PDF)")
            if signals["text_pages"] > 0:
                hints.append(f"부분 스캔 의심: 표본 {len(signals['sampled_pages'])}쪽 중 {signals['text_pages']}쪽만 텍스트")
        if signals["pua_per_10k"] >= PUA_PER_10K_THRESHOLD:
            hints.append("수식이 있는 시험지 (PUA 밀도 ≥100/1만 자: LlamaParse v2 유일 Primary, ODL·Upstage Primary 부적격)")
        if signals["latin_ratio"] >= LATIN_RATIO_THRESHOLD:
            hints.append("영어 비율 ≥50% (Mistral Primary 고려 조건)")
        if has_text_layer and tier in ("large", "xlarge"):
            hints.append("ODL Primary 채택 전 본문 숫자 검증")
        if tier == "small":
            hints.append("PDF Read 도구의 시각 렌더링 = ground truth (≤20p)")
    if lang != "ko":
        hints.append("비한국어 문서 조건 정밀화")
    return hints


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    if len(sys.argv) < 2:
        print("사용법: python assess_document.py <파일경로> [--lang ko]")
        return 1

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
        return 1

    ext = os.path.splitext(file_path)[1].lower()
    fmt = SUPPORTED_FORMATS.get(ext)
    if not fmt:
        print(f"오류: 지원하지 않는 파일 형식입니다: {ext}", file=sys.stderr)
        print(f"지원 형식: {', '.join(SUPPORTED_FORMATS.keys())}", file=sys.stderr)
        return 1

    result = {
        "file": os.path.basename(file_path),
        "format": fmt,
    }

    if fmt == "pdf":
        pdf_info = assess_pdf(file_path)
        if pdf_info is None:
            return 1
        result.update(pdf_info)
    else:
        # 비PDF: 페이지 개념 없음, 파일 크기 기반 간이 판단
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        result["size_mb"] = round(size_mb, 1)
        result["pages"] = None
        result["has_text_layer"] = True  # 비PDF는 텍스트 기반
        result["table_hint"] = fmt == "xlsx"
        result["signals"] = {"sampled_pages": [], "text_pages": 0, "pua_per_10k": 0.0, "latin_ratio": 0.0}
        if fmt == "hwpx":
            result["tier"] = "hwpx"  # 로컬 hwpx_local 우선 + Upstage 폴백
        elif fmt == "hwp":
            result["tier"] = "hwpx"  # HWPX 변환 후 hwpx 티어로 처리(직접은 Upstage)
        elif fmt == "xlsx":
            result["tier"] = "xlsx"
        elif fmt == "docx":
            result["tier"] = "docx"
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
    result["rule_hints"] = rule_hints(
        fmt, result["tier"], result.get("has_text_layer", True),
        result.get("table_hint", False), result["signals"], lang,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
