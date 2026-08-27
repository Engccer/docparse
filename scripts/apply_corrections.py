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
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys

COLS = ["문서", "원본 쪽", "원문", "수정문", "유형", "처리", "근거", "비고"]


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
    pages = load_pages(args.pdf) if args.pdf else None
    errors = []
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
        text = text.replace(src, dst)
        applied += cnt
        print(f"[적용] {r['유형']} | {src!r} → {dst!r} ×{cnt}")
        if dst and src in dst:
            continue
        if src in text:
            errors.append(f"치환 후 잔존: {src!r}")
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
