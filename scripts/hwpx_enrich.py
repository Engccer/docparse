#!/usr/bin/env python3
"""hwpx-tomd 출력(Markdown)에 HWPX 원본의 서식·구조 메타를 결정론적으로 입힌다.

hwpx_local(hwpx-tomd)은 본문·표를 정확히 옮기지만 다음 정보를 버린다.
  ① 제목 수준(개요 스타일)  ② 취소선·글자색 런  ③ 원본 쪽 번호(PDF 인쇄본 기준)
이 스크립트는 같은 HWPX의 header.xml(charPr·style)과 section*.xml을 다시 읽어
  ① 스타일 → `#` 제목 승격  ② `~~취소선~~`·`<mark>강조색</mark>`  ③ `<!-- p.N -->`
을 hwpx-tomd 출력 위에 **문단 단위 정확 일치**로만 덧입힌다(추론 없음). 일치하지
않은 항목은 보고서에 남기고 조용히 넘어가지 않는다.

쪽 번호는 kordoc 등의 추정 페이지네이션이 아니라 **인쇄 PDF의 실제 쪽**을 쓴다
(`--pdf` 지정 시 pdftotext로 쪽별 텍스트를 뽑아 문단을 정렬). PDF 바닥글의 인쇄
번호가 있으면 그 번호를, 없으면 PDF 순번을 적는다.

사용 예:
  python hwpx_enrich.py --hwpx 보고서.hwpx --md 보고서_hwpxlocal.md \
      --pdf 보고서.pdf --heading "바탕글 사본6:1,개요 2:2,개요 3:3,개요 4:4,개요 5:5,개요 6:6" \
      --drop-style 간지번호,장숫자 --drop-regex '^:: 장애유형별|^P∙A∙R∙T$' \
      --mark-color 0000FF,0611F2 --out 보고서_enriched.md --report report.json

원칙: 입력 md의 본문 글자는 바꾸지 않는다(제목 기호·마커·주석·삭제 규칙에 걸린 줄만 다룬다).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from xml.etree import ElementTree as ET

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
}


def local(tag: str) -> str:
    return tag.split("}")[-1]


def norm_ws(s: str) -> str:
    return " ".join(s.split())


# ----------------------------------------------------------------------------
# HWPX 읽기
# ----------------------------------------------------------------------------
def read_header(z: zipfile.ZipFile):
    root = ET.fromstring(z.read("Contents/header.xml"))
    styles = {}
    for st in root.iter(f"{{{NS['hh']}}}style"):
        styles[st.get("id")] = st.get("name", "")
    charpr = {}
    for cp in root.iter(f"{{{NS['hh']}}}charPr"):
        strike = False
        so = cp.find("hh:strikeout", NS)
        if so is not None and (so.get("shape") or "NONE").upper() != "NONE":
            strike = True
        color = (cp.get("textColor") or "").lstrip("#").upper()
        charpr[cp.get("id")] = {"strike": strike, "color": color}
    return styles, charpr


def t_text(t_elem) -> str:
    """hwpx-tomd의 t_full_text와 같은 규칙: tab/lineBreak는 공백, tail 보존."""
    parts = [t_elem.text or ""]
    for child in t_elem:
        if local(child.tag) in ("tab", "lineBreak", "br"):
            parts.append(" ")
        else:
            parts.append("".join(child.itertext()))
        parts.append(child.tail or "")
    return "".join(parts)


def para_runs(p_elem, charpr, mark_colors):
    """문단 직속 run들의 (텍스트, strike, mark) 목록. 중첩 표·글상자는 제외."""
    runs = []
    for run in p_elem.findall("hp:run", NS):
        cp = charpr.get(run.get("charPrIDRef"), {"strike": False, "color": ""})
        txt = "".join(t_text(t) for t in run.findall("hp:t", NS))
        if not txt:
            continue
        runs.append((txt, cp["strike"], cp["color"] in mark_colors))
    return runs


def annotate(runs) -> tuple[str, str]:
    """(원문 정규화, 주석 적용 정규화). 인접 동일 서식 런은 합치고 마커 안쪽 공백은 밖으로 뺀다."""
    plain = norm_ws("".join(r[0] for r in runs))
    merged = []
    for txt, strike, mark in runs:
        if merged and merged[-1][1] == strike and merged[-1][2] == mark:
            merged[-1][0] += txt
        else:
            merged.append([txt, strike, mark])
    out = []
    for txt, strike, mark in merged:
        if not (strike or mark):
            out.append(txt)
            continue
        lead = txt[: len(txt) - len(txt.lstrip())]
        trail = txt[len(txt.rstrip()):]
        core = txt.strip()
        if not core:
            out.append(txt)
            continue
        if mark:
            core = f"<mark>{core}</mark>"
        if strike:
            core = f"~~{core}~~"
        out.append(lead + core + trail)
    return plain, norm_ws("".join(out))


def walk_sections(z: zipfile.ZipFile, charpr, mark_colors):
    """section*.xml을 순서대로 걸어 (최상위 문단 목록, 서식 주석 목록)을 만든다."""
    names = sorted(
        (n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)),
        key=lambda n: int(re.search(r"(\d+)", n).group(1)),
    )
    top_paras = []  # (plain, style_id)  최상위 문단 + 머리말(header ctrl) 문단, 읽기 순서
    all_style_text = defaultdict(set)  # style_id -> 모든 깊이의 문단 텍스트(삭제·간지 판정용)
    annots = []  # (plain, annotated) where annotated != plain
    for name in names:
        raw = z.read(name)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            raw = re.sub(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b"", raw)
            root = ET.fromstring(raw)
        # 최상위 문단: <hs:sec> 직속 <hp:p>
        for p in root.findall("hp:p", NS):
            runs = para_runs(p, charpr, mark_colors)
            plain = norm_ws("".join(r[0] for r in runs))
            top_paras.append((plain, p.get("styleIDRef")))
            # 구역 머리말(header ctrl)의 문단: hwpx-tomd가 본문 자리에 한 번 내보낸다(부 제목 등)
            for hdr in p.findall("hp:run/hp:ctrl/hp:header", NS):
                for hp_ in hdr.iter(f"{{{NS['hp']}}}p"):
                    r2 = para_runs(hp_, charpr, mark_colors)
                    t2 = norm_ws("".join(r[0] for r in r2))
                    if t2:
                        top_paras.append((t2, hp_.get("styleIDRef")))
        for p in root.iter(f"{{{NS['hp']}}}p"):
            runs = para_runs(p, charpr, mark_colors)
            plain = norm_ws("".join(r[0] for r in runs))
            if plain:
                all_style_text[p.get("styleIDRef")].add(plain)
        # 모든 문단(중첩 포함)의 서식 주석
        for p in root.iter(f"{{{NS['hp']}}}p"):
            runs = para_runs(p, charpr, mark_colors)
            if not any(r[1] or r[2] for r in runs):
                continue
            plain, ann = annotate(runs)
            if plain and ann != plain:
                annots.append((plain, ann))
    return top_paras, annots, all_style_text


# ----------------------------------------------------------------------------
# Markdown 세그먼트 처리 (hwpx-tomd 출력 규칙과 대칭)
# ----------------------------------------------------------------------------
CELL_SPLIT = re.compile(r"(?<!\\) \| ")


def split_row(line: str):
    """'| a | b |' → ['a','b'] (셀 안 \\| 보존). 구분선·비표 줄은 None."""
    if not (line.startswith("| ") and line.endswith(" |")):
        return None
    inner = line[2:-2]
    return CELL_SPLIT.split(inner)


def join_row(cells) -> str:
    return "| " + " | ".join(cells) + " |"


def apply_annotations(lines, annots, report):
    """세그먼트(줄 / 셀 / 셀 내 <br> 조각)가 원문과 정확히 같을 때만 주석본으로 치환."""
    table = {}
    for plain, ann in annots:
        table.setdefault(plain, ann)
    esc = {p.replace("|", "\\|"): a.replace("|", "\\|") for p, a in table.items()}
    hit = Counter()
    out = []
    for line in lines:
        cells = split_row(line)
        if cells is None:
            if line in table:
                hit[line] += 1
                out.append(table[line])
            else:
                out.append(line)
            continue
        new_cells = []
        for cell in cells:
            parts = cell.split("<br>")
            new_parts = []
            for seg in parts:
                if seg in esc:
                    hit[seg] += 1
                    new_parts.append(esc[seg])
                else:
                    new_parts.append(seg)
            new_cells.append("<br>".join(new_parts))
        out.append(join_row(new_cells))
    unmatched = [p for p in table if p not in hit and p.replace("|", "\\|") not in hit]
    report["annotation"] = {
        "unique_paragraphs": len(table),
        "replaced_segments": sum(hit.values()),
        "unmatched": unmatched,
    }
    return out


def align_top_paragraphs(lines, top_paras, report):
    """최상위 문단을 md 비표 줄과 순차 정렬. 반환: {line_idx: style_id}."""
    idx_by_text = defaultdict(list)
    for i, line in enumerate(lines):
        if line and split_row(line) is None:
            idx_by_text[line].append(i)
    cursor = 0
    mapping = {}
    missed = []
    for plain, style in top_paras:
        if not plain:
            continue
        cands = [i for i in idx_by_text.get(plain, []) if i >= cursor]
        if not cands:
            missed.append(plain[:60])
            continue
        i = cands[0]
        mapping[i] = style
        cursor = i + 1
    report["alignment"] = {
        "top_paragraphs": sum(1 for p, _ in top_paras if p),
        "aligned": len(mapping),
        "missed_sample": missed[:30],
        "missed": len(missed),
    }
    return mapping


# ----------------------------------------------------------------------------
# PDF 쪽 정렬
# ----------------------------------------------------------------------------
def pdf_pages(pdf_path: str):
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True).stdout).group(1))
    pages = []
    for p in range(1, n + 1):
        t = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-layout", pdf_path, "-"], capture_output=True, text=True).stdout
        nonempty = [l.strip() for l in t.split("\n") if l.strip()]
        last = nonempty[-1] if nonempty else ""
        printed = int(last) if re.fullmatch(r"\d{1,4}", last) else None
        pages.append({"pdf": p, "printed": printed, "key": re.sub(r"[\W_]+", "", t)})
    return pages


def page_label(pg, label_fn=None):
    if label_fn:
        return label_fn(pg)
    return str(pg["printed"]) if pg["printed"] else f"pdf{pg['pdf']}"


def assign_pages(lines, pages, report, heading_idx=frozenset(), min_len=10, key_len=16, heading_min_len=5):
    """각 줄의 대표 세그먼트를 PDF 쪽 텍스트에서 찾아, 쪽 번호가 문서 순서대로 **단조 증가**하는
    가장 긴 정렬(LIS)을 고른다. 반환: [page_index or None].

    탐색창을 앞으로만 넓히는 방식은 반복 문구(같은 조사지가 학교급별로 4번 실리는 등)에
    한 번 걸려 앞으로 튀면 그 뒤 줄이 전부 못 붙는다. 전역 LIS는 후보를 모두 모아 놓고
    문서 순서와 가장 잘 맞는 조합을 고르므로 그런 오탐이 자연히 버려진다.
    """
    import bisect

    cands = []  # (line_idx, [page_idx...])
    tried = 0
    for i, line in enumerate(lines):
        if not line or line.startswith("<!--") or line.startswith("| --- "):
            continue
        cells = split_row(line)
        seg = line
        if cells is not None:
            seg = max((c.split("<br>")[0] for c in cells), key=lambda c: len(re.sub(r"[\W_]+", "", c)), default="")
        is_heading = i in heading_idx
        seg = re.sub(r"</?mark>|~~|^#+\s*", "", seg)
        key = re.sub(r"[\W_]+", "", seg)
        if len(key) < (heading_min_len if is_heading else min_len):
            continue
        key = key[:key_len]
        tried += 1
        hits = [k for k, pg in enumerate(pages) if key in pg["key"]]
        if hits and len(hits) <= 12:
            cands.append((i, hits))
    # LIS(비감소) over candidates: 각 줄은 후보를 내림차순으로 넣어 같은 줄이 두 번 쓰이지 않게 한다
    tails = []  # (page, node_id)
    nodes = []  # (line_idx, page, prev_node)
    for li, hits in cands:
        for pg in sorted(hits, reverse=True):
            pos = bisect.bisect_right([t[0] for t in tails], pg)
            prev = tails[pos - 1][1] if pos > 0 else -1
            nodes.append((li, pg, prev))
            nid = len(nodes) - 1
            if pos == len(tails):
                tails.append((pg, nid))
            else:
                tails[pos] = (pg, nid)
    result = [None] * len(lines)
    found = 0
    nid = tails[-1][1] if tails else -1
    while nid >= 0:
        li, pg, prev = nodes[nid]
        result[li] = pg
        found += 1
        nid = prev
    # 제목 줄은 자기 매칭이 없으면 바로 뒤 본문(같은 쪽일 가능성이 큼)의 쪽을 물려받는다
    for i, line in enumerate(lines):
        if i in heading_idx and result[i] is None:
            for j in range(i + 1, min(len(lines), i + 8)):
                if result[j] is not None:
                    result[i] = result[j]
                    break
    report["pages"] = {"lines_tried": tried, "candidates": len(cands), "lines_found": found,
                       "last_pdf_page": pages[max(r for r in result if r is not None)]["pdf"] if found else None}
    return result


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def parse_map(spec: str):
    out = {}
    for item in filter(None, (s.strip() for s in spec.split(","))):
        k, v = item.rsplit(":", 1)
        out[k.strip()] = int(v)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hwpx", required=True)
    ap.add_argument("--md", required=True, help="hwpx-tomd 출력 md")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", help="JSON 보고서 경로")
    ap.add_argument("--pdf", help="인쇄 PDF(쪽 번호 정렬용, pdftotext 필요)")
    ap.add_argument("--heading", default="", help="'스타일명|ID:레벨,...' 예: '개요 2:2,개요 3:3'")
    ap.add_argument("--heading-regex", default="", help="'정규식:레벨;;정규식:레벨' 최상위 줄에 적용")
    ap.add_argument("--part-title-style", default="", help="간지 제목 스타일명. 직전 H1의 꼬리와 같으면 삭제, 아니면 --part-title-level 제목")
    ap.add_argument("--part-title-level", type=int, default=2)
    ap.add_argument("--drop-style", default="", help="삭제할 스타일명|ID 목록(쉼표)")
    ap.add_argument("--drop-regex", default="", help="삭제할 최상위 줄 정규식(|로 이어 씀)")
    ap.add_argument("--drop-table-regex", default="", help="모든 셀이 이 정규식 또는 간지 텍스트에 걸리는 레이아웃 표 삭제")
    ap.add_argument("--mark-color", default="0000FF", help="<mark>로 감쌀 글자색 hex 목록(쉼표, # 없이)")
    ap.add_argument("--page-comment", default="<!-- p.{label} (pdf {pdf}) -->")
    ap.add_argument("--page-label-rule", default="", help="'lo-hi:prefix' 목록(쉼표). 예 '1-12:목차 ,13-24:Ⅰ-'")
    args = ap.parse_args()

    report = {}
    z = zipfile.ZipFile(args.hwpx)
    styles, charpr = read_header(z)
    name_to_id = defaultdict(list)
    for sid, nm in styles.items():
        name_to_id[nm].append(sid)

    def resolve(spec):
        ids = set()
        for k in filter(None, (s.strip() for s in spec.split(","))):
            ids.update(name_to_id.get(k, [k] if k.isdigit() else []))
        return ids

    heading_by_style = {}
    for k, lvl in parse_map(args.heading).items():
        for sid in (name_to_id.get(k) or ([k] if k.isdigit() else [])):
            heading_by_style[sid] = lvl
    drop_styles = resolve(args.drop_style)
    part_styles = resolve(args.part_title_style)
    mark_colors = {c.strip().upper() for c in args.mark_color.split(",") if c.strip()}
    heading_regex = []
    if args.heading_regex:
        for item in args.heading_regex.split(";;"):
            rx, lvl = item.rsplit(":", 1)
            heading_regex.append((re.compile(rx), int(lvl)))
    drop_rx = re.compile(args.drop_regex) if args.drop_regex else None
    drop_tbl_rx = re.compile(args.drop_table_regex) if args.drop_table_regex else None

    top_paras, annots, all_style_text = walk_sections(z, charpr, mark_colors)
    drop_texts = set()
    for sid in drop_styles:
        drop_texts |= all_style_text.get(sid, set())
    layout_texts = set(drop_texts)
    for sid in part_styles:
        layout_texts |= all_style_text.get(sid, set())
    lines = open(args.md, encoding="utf-8").read().split("\n")

    # 1) 최상위 문단 정렬 → 제목 승격·삭제
    style_at = align_top_paragraphs(lines, top_paras, report)
    heading_level = {}
    drop = set()
    last_h1 = ""
    promoted = Counter()
    for i in sorted(style_at):
        sid = style_at[i]
        line = lines[i]
        if sid in drop_styles:
            drop.add(i)
            continue
        if sid in part_styles:
            if last_h1 and last_h1.endswith(line):
                drop.add(i)
                continue
            heading_level[i] = args.part_title_level
            promoted[f"part:{styles.get(sid)}"] += 1
            continue
        if sid in heading_by_style:
            lvl = heading_by_style[sid]
            heading_level[i] = lvl
            promoted[styles.get(sid, sid)] += 1
            if lvl == 1:
                last_h1 = line
    # 간지 레이아웃 표(모든 셀이 간지 제목/번호)와 글상자 텍스트 줄 삭제
    i = 0
    while i < len(lines):
        cells = split_row(lines[i])
        if cells is None:
            i += 1
            continue
        j = i
        block_cells = []
        while j < len(lines) and split_row(lines[j]) is not None:
            if not lines[j].startswith("| --- "):
                block_cells += split_row(lines[j])
            j += 1
        nonempty = [c for c in block_cells if c.strip()]
        if nonempty and all(c in layout_texts or (drop_tbl_rx and drop_tbl_rx.search(c)) for c in nonempty):
            drop.update(range(i, j))
            promoted["dropped-layout-table"] += 1
        i = j
    for i, line in enumerate(lines):
        if i in heading_level or i in drop or split_row(line) is not None or not line:
            continue
        if line in drop_texts:
            drop.add(i)
            continue
        if drop_rx and drop_rx.search(line):
            drop.add(i)
            continue
        for rx, lvl in heading_regex:
            if rx.search(line):
                heading_level[i] = lvl
                promoted[f"regex:{rx.pattern}"] += 1
                break
    report["headings"] = dict(promoted)
    report["dropped_lines"] = len(drop)

    # 2) 서식 주석
    lines = apply_annotations(lines, annots, report)

    # 3) 쪽 정렬
    page_idx = None
    pages = None
    if args.pdf:
        pages = pdf_pages(args.pdf)
        page_idx = assign_pages(lines, pages, report, heading_idx=set(heading_level))
        rules = []
        for item in filter(None, (s.strip() for s in args.page_label_rule.split(","))):
            rng, prefix = item.split(":", 1)
            lo, hi = rng.split("-")
            rules.append((int(lo), int(hi), prefix))

        def label(pg):
            base = str(pg["printed"]) if pg["printed"] else f"pdf{pg['pdf']}"
            for lo, hi, prefix in rules:
                if lo <= pg["pdf"] <= hi:
                    return prefix + base
            return base

    # 4) 출력 조립
    out = []
    last_page_written = None
    cur_page = None
    for i, line in enumerate(lines):
        if i in drop:
            continue
        if page_idx is not None and page_idx[i] is not None:
            cur_page = page_idx[i]
        if i in heading_level:
            if pages is not None and cur_page is not None and cur_page != last_page_written:
                pg = pages[cur_page]
                out.append(args.page_comment.format(label=label(pg), pdf=pg["pdf"]))
                last_page_written = cur_page
            if out and out[-1] != "":
                out.append("")
            out.append("#" * heading_level[i] + " " + line)
            out.append("")
            continue
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    open(args.out, "w", encoding="utf-8").write(text)
    if args.report:
        json.dump(report, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if not isinstance(vv, list)}) for k, v in report.items()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
