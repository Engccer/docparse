"""ODT 파싱 결과 검증: 원본 content.xml 문단과 출력 마크다운 전수 대조(SKILL.md ODT 규칙의 코드화).

검사(하나라도 걸리면 FAIL):
  - missing: 비어 있지 않은 문단(text:p·text:h의 자기 글. 글상자·각주 안 문단은 따로 셈)이 출력에 없음
  - order: 출력에 있지만 원본 읽기 순서와 어긋남
  - duplicates: 원본보다 많이 나옴(공백 뺀 6자 이상 문단만)
  - table_rows: 표 한 행의 셀 글이 출력의 한 행(파이프 표 한 줄 또는 HTML <tr>)에 순서대로 모이지 않음
    (머리행 여부를 함께 적는다)
  - metadata_leaks: meta.xml 제목·주제·설명·키워드나 책갈피 이름이 원본 본문보다 많이 출력에 나옴
    (본문에도 같은 글이 있으면 그 횟수까지는 정상)
보고만 하는 항목(판정에 넣지 않음):
  - spacing_only: 띄어쓰기만 달라 공백을 빼야 일치한 문단
  - header_footer: styles.xml 머리말·꼬리말 문단의 출력 존재(일반 머리말·꼬리말은 빼도 된다)
  - images: 내장 이미지 수와 출력의 이미지 참조 수. 파서는 ODT 이미지를 추출하지 않으므로
    텍스트 PASS와 별개로 "not_extracted"를 표시한다.

Usage:
    python odt_verify.py <원본.odt> <출력.md> [--json]

종료 코드: PASS 0, FAIL 1, 입력 오류 2.
"""

import html
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
XLINK = "http://www.w3.org/1999/xlink"
DC = "http://purl.org/dc/elements/1.1/"
META = "urn:oasis:names:tc:opendocument:xmlns:meta:1.0"


def q(ns, tag):
    return f"{{{ns}}}{tag}"


PARA = {q(TEXT, "p"), q(TEXT, "h")}
SKIP = {q(OFFICE, "annotation"), q(TEXT, "tracked-changes"), q(TEXT, "note-citation")}
HTML_TAG = re.compile(r"</?(?:table|thead|tbody|tfoot|tr|td|th|br|p|div|span|img|sup|sub|b|i|u|strong|em)\b[^>]*>", re.I)
MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")
DUP_MIN = 6


def norm(s):
    return " ".join(s.split())


def nospace(s):
    return "".join(s.split())


def own_text(el):
    """문단 자기 글. 안쪽 문단(글상자·각주 본문)과 주석·변경 추적은 빼고 공백 요소는 공백으로."""
    parts = [el.text or ""]
    for child in el:
        tag = child.tag
        if tag in PARA or tag in SKIP or tag == q(DRAW, "frame") or tag == q(TEXT, "note"):
            pass
        elif tag == q(TEXT, "s"):
            parts.append(" " * int(child.get(q(TEXT, "c"), "1")))
        elif tag in (q(TEXT, "tab"), q(TEXT, "line-break")):
            parts.append(" ")
        else:
            parts.append(own_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def walk(el, paras, tables, ctx):
    """문서 순서대로 문단을 모으고, 표는 행마다 (머리행 여부, [셀 문단 목록])로 모은다."""
    for child in el:
        tag = child.tag
        if tag in SKIP:
            continue
        if tag in PARA:
            text = norm(own_text(child))
            if text:
                paras.append(text)
                if ctx.get("cell") is not None:
                    ctx["cell"].append(text)
            walk(child, paras, tables, ctx)
        elif tag == q(TABLE, "table"):
            table = {"rows": []}
            tables.append(table)
            walk(child, paras, tables, {"table": table, "header": False, "cell": None, "outer": ctx.get("cell")})
        elif tag == q(TABLE, "table-header-rows"):
            walk(child, paras, tables, {**ctx, "header": True})
        elif tag == q(TABLE, "table-row"):
            row = {"header": ctx["header"], "cells": []}
            ctx["table"]["rows"].append(row)
            walk(child, paras, tables, {**ctx, "row": row})
        elif tag == q(TABLE, "table-cell"):
            cell = []
            walk(child, paras, tables, {**ctx, "cell": cell})
            if cell:
                ctx["row"]["cells"].append(" ".join(cell))
                if ctx.get("outer") is not None:  # 중첩 표: 바깥 셀에도 글을 넘긴다
                    ctx["outer"].extend(cell)
        else:
            walk(child, paras, tables, ctx)


def read_odt(path):
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "content.xml" not in names:
            raise ValueError("content.xml이 없다(ODT가 아님)")
        content = ET.fromstring(zf.read("content.xml"))
        styles = ET.fromstring(zf.read("styles.xml")) if "styles.xml" in names else None
        meta = ET.fromstring(zf.read("meta.xml")) if "meta.xml" in names else None
    body = content.find(f"{q(OFFICE, 'body')}/{q(OFFICE, 'text')}")
    if body is None:
        raise ValueError("office:text 본문이 없다(텍스트 문서가 아님)")
    paras, tables = [], []
    walk(body, paras, tables, {"cell": None})

    header_footer = []
    images = set()
    for root in (content, styles):
        if root is None:
            continue
        for img in root.iter(q(DRAW, "image")):
            href = img.get(q(XLINK, "href"))
            if href:
                images.add(href)
    if styles is not None:
        for page in styles.iter(q(STYLE, "master-page")):
            for part in page:
                if part.tag.startswith(f"{{{STYLE}}}header") or part.tag.startswith(f"{{{STYLE}}}footer"):
                    hf = []
                    walk(part, hf, [], {"cell": None})
                    header_footer.extend(hf)

    metadata = set()
    if meta is not None:
        for tag in (q(DC, "title"), q(DC, "subject"), q(DC, "description"), q(META, "keyword")):
            for el in meta.iter(tag):
                if el.text and norm(el.text):
                    metadata.add(norm(el.text))
    for tag in ("bookmark", "bookmark-start"):
        for el in content.iter(q(TEXT, tag)):
            name = el.get(q(TEXT, "name"))
            if name and norm(name):
                metadata.add(norm(name))
    return {"paragraphs": paras, "tables": tables, "header_footer": header_footer,
            "images": sorted(images), "metadata": sorted(metadata)}


def clean(s):
    s = HTML_TAG.sub(" ", s)
    s = MD_ESCAPE.sub(r"\1", s)
    s = s.replace("**", "").replace("__", "")
    return norm(html.unescape(s))


def row_units(md):
    """파이프 표는 한 줄, HTML 표는 <tr>…</tr> 하나(여러 줄이어도)를 한 행 단위로."""
    units = []
    for chunk in re.split(r"</tr\s*>", md, flags=re.I):
        start = chunk.lower().rfind("<tr")
        if start >= 0:
            units.extend(chunk[:start].split("\n"))
            units.append(chunk[start:])
        else:
            units.extend(chunk.split("\n"))
    return [u for u in (clean(x) for x in units) if u]


def in_order(unit, cells):
    pos = 0
    for c in cells:
        found = unit.find(c, pos)
        if found < 0:
            return False
        pos = found + len(c)
    return True


def verify(odt_path, md_text):
    src = read_odt(odt_path)
    out = clean(md_text)
    out_ns = nospace(out)
    joined = " ".join(src["paragraphs"])

    missing, spacing_only, order, duplicates = [], [], [], []
    cursor = 0
    for p in src["paragraphs"]:
        if p not in out:
            (spacing_only if nospace(p) in out_ns else missing).append(p)
            continue
        found = out.find(p, cursor)
        if found < 0:
            order.append(p)
        else:
            cursor = found + len(p)
    for p in dict.fromkeys(src["paragraphs"]):
        if len(nospace(p)) >= DUP_MIN and out.count(p) > joined.count(p):
            duplicates.append({"text": p, "source": joined.count(p), "output": out.count(p)})

    units = row_units(md_text)
    table_rows = []
    for t_index, table in enumerate(src["tables"], 1):
        for r_index, row in enumerate(table["rows"], 1):
            if row["cells"] and not any(in_order(u, row["cells"]) for u in units):
                table_rows.append({"table": t_index, "row": r_index, "header": row["header"], "cells": row["cells"]})

    leaks = []
    for m in src["metadata"]:
        if out.count(m) > joined.count(m):
            leaks.append({"text": m, "source_body": joined.count(m), "output": out.count(m)})

    img_refs = len(re.findall(r"!\[[^\]]*\]\(", md_text)) + len(re.findall(r"<img\b", md_text, re.I))
    n_img = len(src["images"])
    images = {"embedded": n_img, "output_refs": img_refs,
              "status": "none" if n_img == 0 else ("referenced" if img_refs else "not_extracted")}

    failed = missing or order or duplicates or table_rows or leaks
    return {
        "verdict": "FAIL" if failed else "PASS",
        "paragraphs": len(src["paragraphs"]),
        "tables": len(src["tables"]),
        "missing": missing, "order": order, "duplicates": duplicates,
        "table_rows": table_rows, "metadata_leaks": leaks,
        "spacing_only": spacing_only,
        "header_footer": [{"text": t, "in_output": t in out} for t in src["header_footer"]],
        "images": images,
    }


def render(r):
    lines = [f"판정: {r['verdict']} (문단 {r['paragraphs']}개, 표 {r['tables']}개)"]
    for p in r["missing"]:
        lines.append(f"  누락: {p}")
    for p in r["order"]:
        lines.append(f"  순서 어긋남: {p}")
    for d in r["duplicates"]:
        lines.append(f"  중복: {d['text']} (원본 {d['source']}회, 출력 {d['output']}회)")
    for t in r["table_rows"]:
        kind = "머리행" if t["header"] else "행"
        lines.append(f"  표 {t['table']} {kind} {t['row']} 셀 대응 실패: {' | '.join(t['cells'])}")
    for m in r["metadata_leaks"]:
        lines.append(f"  메타데이터 안내문 혼입: {m['text']} (본문 {m['source_body']}회, 출력 {m['output']}회)")
    for p in r["spacing_only"]:
        lines.append(f"  참고(띄어쓰기만 다름): {p}")
    for h in r["header_footer"]:
        lines.append(f"  참고(머리말·꼬리말 {'있음' if h['in_output'] else '없음'}): {h['text']}")
    img = r["images"]
    if img["status"] == "not_extracted":
        lines.append(f"  이미지: 내장 {img['embedded']}개 미추출(텍스트 판정과 별개. 이미지 내용은 따로 판독)")
    elif img["status"] == "referenced":
        lines.append(f"  이미지: 내장 {img['embedded']}개, 출력 참조 {img['output_refs']}개(내용 일치는 미검증)")
    return "\n".join(lines)


def main(argv):
    args = [a for a in argv if a != "--json"]
    if len(args) != 2 or any(a.startswith("-") for a in args):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        with open(args[1], encoding="utf-8") as f:
            md = f.read()
        result = verify(args[0], md)
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError, UnicodeDecodeError) as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if "--json" in argv else render(result))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
