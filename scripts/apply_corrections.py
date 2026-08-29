#!/usr/bin/env python3
"""정본 수정 목록(CSV)을 마크다운 정본에 적용하고 결과를 검증한다.

원본과 달라지는 모든 변경(오탈자 교정·개인정보 삭제·표기 정규화)은 손으로 고치지 않고
이 CSV를 거친다. CSV가 곧 「수정 목록」이며, 정본을 재생성해도 같은 CSV를 다시 적용하면
같은 결과가 나온다(재현성).

CSV 열(UTF-8 BOM, 첫 줄 머리글):
  문서, 원본 쪽, 원문, 수정문, 유형, 처리, 근거, 비고
  - 유형: 오탈자 / 개인정보 / 표기 정규화 / 원본 결함 / 법령 갱신 / 확인 필요
  - 처리: 적용 → 원문을 수정문으로 치환 / 기록만 → 치환하지 않고 목록에만 남김
  - 원본 쪽: 비워 두면 --pdf-pages(hwpx_enrich.py가 만든 쪽 텍스트 JSON 또는 PDF 경로)로 채운다

사용:
  python apply_corrections.py --csv "정본 수정 목록.csv" --doc "2023 최종보고서" --in enriched.md --out final.md [--pdf 원본.pdf] [--write-pages]

검증: 처리=적용 행은 원문이 입력에 1회 이상 있어야 하며(0회면 오류 종료), 치환 후 원문이
남아 있지 않아야 한다. 치환 건수는 표준출력에 행별로 보고한다.

치환 범위(2026-08-31): 입력 마크다운에 `hwpx_enrich.py`가 넣은 쪽 주석(`<!-- p.N ... -->`)이
있고 행의 「원본 쪽」이 채워져 있으면 **그 쪽 구간 안에서만** 치환한다(종전에는 쪽을 읽고도
문서 전체를 바꿔, 5쪽의 오인식 `2025`를 고치려다 다른 쪽의 진짜 `2025`까지 바꿨다).
쪽 주석이 없거나 원본 쪽이 비어 있으면 전역 치환이며, 그때 원문이 2회 이상 맞으면
「표기 정규화」 유형이 아닌 한 경고를 낸다.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys

COLS = ["문서", "원본 쪽", "원문", "수정문", "유형", "처리", "근거", "비고"]
PAGE_MARK = re.compile(r"<!--\s*p\.(\d+)\b[^>]*-->")


def split_by_page(text: str):
    """쪽 주석 기준 구간 목록 [(쪽 번호 또는 None, 구간 문자열), ...]. 주석이 없으면 None."""
    marks = list(PAGE_MARK.finditer(text))
    if not marks:
        return None
    segments = [(None, text[:marks[0].start()])]
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(text)
        segments.append((int(m.group(1)), text[m.start():end]))
    return segments


def replace_in_pages(segments, pages_wanted, src, dst):
    """지정 쪽 구간에서만 치환. (새 구간 목록, 치환 횟수)"""
    count = 0
    out = []
    for page, seg in segments:
        if page in pages_wanted and src in seg:
            count += seg.count(src)
            seg = seg.replace(src, dst)
        out.append((page, seg))
    return out, count


def load_pages(pdf: str):
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout).group(1))
    pages = []
    for p in range(1, n + 1):
        t = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-layout", pdf, "-"], capture_output=True, text=True).stdout
        nonempty = [l.strip() for l in t.split("\n") if l.strip()]
        last = nonempty[-1] if nonempty else ""
        pages.append({"pdf": p, "printed": int(last) if re.fullmatch(r"\d{1,4}", last) else None, "key": re.sub(r"[\W_]+", "", t)})
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--doc", required=True, help="CSV '문서' 열과 일치하는 행만 적용")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pdf", help="원본 쪽 자동 채움용 PDF")
    ap.add_argument("--write-pages", action="store_true", help="채운 원본 쪽을 CSV에 다시 쓴다")
    args = ap.parse_args()

    with open(args.csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in COLS if rows and c not in rows[0]]
    if missing:
        sys.exit(f"CSV 열 누락: {missing}")

    text = open(args.inp, encoding="utf-8").read()
    segments = split_by_page(text)
    pages = load_pages(args.pdf) if args.pdf else None
    errors = []
    warnings = []
    applied = 0
    for r in rows:
        if r["문서"] != args.doc:
            continue
        src, dst = r["원문"], r["수정문"]
        cnt = text.count(src) if src else 0
        if pages is not None and not r["원본 쪽"].strip() and src:
            key = re.sub(r"[\W_]+", "", src)
            hits = [pg for pg in pages if key and key in pg["key"]]
            if hits:
                r["원본 쪽"] = ", ".join(str(pg["printed"] or f"pdf{pg['pdf']}") for pg in hits[:8]) + (" 외" if len(hits) > 8 else "")
        if r["처리"].strip() != "적용":
            print(f"[기록만] {r['유형']} | {src[:40]!r} (본문 {cnt}회)")
            continue
        if cnt == 0:
            errors.append(f"원문 없음: {src!r}")
            continue
        # `pdf7`은 인쇄 쪽 번호가 없는 쪽의 PDF 순번이라 <!-- p.N --> 라벨과 다른 좌표계다.
        # 인쇄 쪽 번호(순수 숫자)만 범위 지정에 쓰고, pdf 접두 값은 전역 경로로 보낸다.
        page_field = r["원본 쪽"] or ""
        wanted = {int(n) for n in re.findall(r"(?<![A-Za-z])\d+", page_field)} - {
            int(n) for n in re.findall(r"pdf(\d+)", page_field)
        }
        if segments is not None and wanted:
            segments, n_scoped = replace_in_pages(segments, wanted, src, dst)
            text = "".join(seg for _, seg in segments)
            if n_scoped == 0:
                errors.append(f"지정 쪽 {sorted(wanted)}에 원문 없음(본문 다른 곳 {cnt}회): {src!r}")
                continue
            applied += n_scoped
            print(f"[적용·쪽 {sorted(wanted)}] {r['유형']} | {src!r} → {dst!r} ×{n_scoped}")
            continue
        if cnt > 1 and r["유형"].strip() != "표기 정규화":
            warnings.append(f"전역 치환 {cnt}회({r['유형']}): {src!r} — 쪽 주석이 없거나 원본 쪽이 비어 범위를 좁히지 못함")
        text = text.replace(src, dst)
        applied += cnt
        print(f"[적용] {r['유형']} | {src!r} → {dst!r} ×{cnt}")
        if dst and src in dst:
            continue
        if src in text:
            errors.append(f"치환 후 잔존: {src!r}")
    for w in warnings:
        print("경고:", w, file=sys.stderr)
    if errors:
        for e in errors:
            print("오류:", e, file=sys.stderr)
        sys.exit(1)
    open(args.out, "w", encoding="utf-8").write(text)
    print(f"완료: {applied}건 치환 → {args.out}")
    if args.write_pages:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows({c: r.get(c, "") for c in COLS} for r in rows)


if __name__ == "__main__":
    main()
