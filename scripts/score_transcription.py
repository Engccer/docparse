# -*- coding: utf-8 -*-
"""
손글씨/OCR 전사 정량 채점기 (docparse). 정본(ground truth) 대비 후보 전사본의 본문 충실도를
학번(또는 임의 ID)별 CER(문자 오류율)·WER(단어 오류율)로 측정하고 micro/macro 집계.

캐스케이드·단독 비전 등 손글씨 파이프라인의 모델·방법 비교(calibration)에 쓴다.
2026-06-23 손글씨 토너먼트에서 정립(handwriting-cascade.md 참조).

사용:
  python score_transcription.py <정본.md> <라벨A>=<후보A.md> <라벨B>=<후보B.md> [...] [--out report.md]
  [--id-pattern '정규식']   # 항목 분할 헤더. 기본 '^##\\s*학번\\s*[:：]\\s*(\\d{5})'

본문 추출: id-pattern 헤더로 분할 → 헤더 줄 제거 → '---'/'>' 줄 제거 → 전체 공백을 단일 공백 정규화.
정규화는 편집 주석(`[...]`, 한글 포함 `(...)`)을 정본·후보 양쪽에서 대칭 제거(정본의 [미작성]·(빈 줄만…),
후보의 [취소선]·(주의:…) 등). 대소문자·문장부호·철자오류는 보존(diplomatic 채점 요소).
정본이 0자(백지)인 항목은 충실도 측정 불가 → 집계 제외(0자는 CER 0/100%만 나와 macro 왜곡).

의존: pip install python-Levenshtein rapidfuzz
"""
import re, sys
import Levenshtein
from rapidfuzz.distance import Levenshtein as RFLev

try:
    sys.stdout.reconfigure(encoding='utf-8')   # Windows cp949 콘솔 안전
except Exception:
    pass

DEFAULT_ID = r'^##\s*학번\s*[:：]\s*(\d{5})'

def parse_md(path, id_re):
    text = open(path, encoding='utf-8').read()
    ms = list(id_re.finditer(text))
    out = {}
    for i, m in enumerate(ms):
        key = m.group(1)
        start = m.end()
        end = ms[i+1].start() if i+1 < len(ms) else len(text)
        chunk = text[start:end]
        body = chunk.split('\n', 1)[1] if '\n' in chunk else ''
        body = re.sub(r'^\s*---+\s*$', ' ', body, flags=re.M)
        body = re.sub(r'^\s*>.*$', ' ', body, flags=re.M)
        out[key] = norm(body)
    return out

def norm(s):
    s = re.sub(r'\[[^\]]*\]', ' ', s)               # 대괄호 편집 마커
    s = re.sub(r'\([^)]*[가-힣][^)]*\)', ' ', s)     # 한글 포함 괄호 보충
    return re.sub(r'\s+', ' ', s).strip()

def cer(ref, hyp):
    if not ref:
        return (0.0 if not hyp else 1.0), len(hyp)
    d = Levenshtein.distance(ref, hyp)
    return d / len(ref), d

def wer(ref, hyp):
    r, h = ref.split(), hyp.split()
    if not r:
        return (0.0 if not h else 1.0), len(h)
    d = RFLev.distance(r, h)
    return d / len(r), d

def main():
    args = sys.argv[1:]
    out_path = None
    id_re = re.compile(DEFAULT_ID, re.M)
    if '--out' in args:
        k = args.index('--out'); out_path = args[k+1]; args = args[:k] + args[k+2:]
    if '--id-pattern' in args:
        k = args.index('--id-pattern'); id_re = re.compile(args[k+1], re.M); args = args[:k] + args[k+2:]
    canon_path = args[0]
    cands = [a.split('=', 1) for a in args[1:]]

    canon = parse_md(canon_path, id_re)
    parsed = {lbl: parse_md(p, id_re) for lbl, p in cands}
    keys = sorted(canon.keys())

    lines = [f"# 전사 정량 채점\n", f"정본: `{canon_path}`  ({len(canon)}항목)\n"]
    for lbl, p in cands:
        miss = [k for k in keys if k not in parsed[lbl]]
        extra = [k for k in parsed[lbl] if k not in canon]
        lines.append(f"- **{lbl}**: `{p}` ({len(parsed[lbl])}항목)"
                     f"{' / 누락 '+str(miss) if miss else ''}{' / 정본외 '+str(extra) if extra else ''}")
    lines.append("")

    agg = {lbl: dict(cdist=0, clen=0, wdist=0, wlen=0, ci_cdist=0, ci_clen=0, cer_list=[], wer_list=[])
           for lbl, _ in cands}
    head = "| ID | 정본 글자수 | " + " | ".join(f"{l} CER%" for l, _ in cands) + " | " + " | ".join(f"{l} WER%" for l, _ in cands) + " |"
    lines += ["## 항목별 정확도 (CER%=문자, WER%=단어)\n", head,
              "|------|------:|" + "------:|"*(len(cands)*2)]
    excluded = []
    for k in keys:
        ref = canon[k]; nonblank = len(ref) > 0
        if not nonblank: excluded.append(k)
        cer_cells, wer_cells = [], []
        for lbl, _ in cands:
            hyp = parsed[lbl].get(k, "")
            cr, cd = cer(ref, hyp); wr, wd = wer(ref, hyp)
            cri, cdi = cer(ref.lower(), hyp.lower())
            if nonblank:
                a = agg[lbl]
                a['cdist'] += cd; a['clen'] += len(ref); a['wdist'] += wd; a['wlen'] += len(ref.split())
                a['ci_cdist'] += cdi; a['ci_clen'] += len(ref)
                a['cer_list'].append(cr); a['wer_list'].append(wr)
            cer_cells.append(f"{(1-cr)*100:.1f}"); wer_cells.append(f"{max(0,1-wr)*100:.1f}")
        mark = " (백지·집계제외)" if not nonblank else ""
        lines.append("| " + " | ".join([k, str(len(ref))] + cer_cells + wer_cells) + f" |{mark}")
    if excluded:
        lines.append(f"\n> 집계 제외(정본 0자/백지): {', '.join(excluded)} (충실도 측정 불가).")

    def mac(xs): return sum(xs)/len(xs) if xs else 0
    metrics = []
    for lbl, _ in cands:
        a = agg[lbl]
        metrics.append((lbl,
            (1-a['cdist']/a['clen'])*100 if a['clen'] else 0,
            (1-a['ci_cdist']/a['ci_clen'])*100 if a['ci_clen'] else 0,
            (1-a['wdist']/a['wlen'])*100 if a['wlen'] else 0,
            (1-mac(a['cer_list']))*100,
            max(0,(1-mac(a['wer_list'])))*100))
    lines += ["\n## 집계\n", "| 지표 | " + " | ".join(l for l, _ in cands) + " |",
              "|------|" + "------:|"*len(cands)]
    for name, idx in [("문자 정확도 (micro, 대소문자 구분)",1), ("문자 정확도 (micro, 대소문자 무시)",2),
                      ("단어 정확도 (micro)",3), ("문자 정확도 (macro)",4), ("단어 정확도 (macro)",5)]:
        lines.append(f"| {name} | " + " | ".join(f"{m[idx]:.2f}%" for m in metrics) + " |")
    best = max(metrics, key=lambda m: m[1])
    lines.append(f"\n## 헤드라인\n- 문자 정확도(micro) 최고: **{best[0]}** = {best[1]:.2f}% (정본과의 차이 {100-best[1]:.2f}%)")

    report = "\n".join(lines)
    if out_path:
        open(out_path, "w", encoding="utf-8").write(report)
        print(f"채점 보고서 저장: {out_path}")
    else:
        print(report)

if __name__ == "__main__":
    main()
