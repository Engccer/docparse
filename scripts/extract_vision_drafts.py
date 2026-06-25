# -*- coding: utf-8 -*-
"""
gvision_parse.py 출력(_gvision.md)에서 페이지별 영어 드래프트 + 저신뢰 목록을 추출해
draft_pNN.txt 로 저장. Vision→Claude 캐스케이드 repair 단계의 입력(handwriting-cascade.md ②).

라틴 글자 포함·한글 미포함 라인만 본문 드래프트로 모은다(한글 양식·자기 점검표 자동 제거).
각 페이지 저신뢰(<0.90) 단어 목록을 "시각 판독 표적"으로 함께 저장.

사용:
  python extract_vision_drafts.py <_gvision.md> [--out-dir <폴더>]
기본 out-dir = <_gvision.md 폴더>/drafts_<base>
"""
import re, os, sys

def main():
    args = sys.argv[1:]
    out_dir = None
    if '--out-dir' in args:
        k = args.index('--out-dir'); out_dir = args[k+1]; args = args[:k] + args[k+2:]
    if not args:
        print("사용: python extract_vision_drafts.py <_gvision.md> [--out-dir <폴더>]"); return
    gv = args[0]
    base = re.sub(r'_gvision$', '', os.path.splitext(os.path.basename(gv))[0])
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(gv) or ".", f"drafts_{base}")
    os.makedirs(out_dir, exist_ok=True)

    text = open(gv, encoding="utf-8").read()
    chunks = re.split(r'^## p\.(\d+)\s*$', text, flags=re.M)  # [pre, '1', body1, '2', body2, ...]
    n = 0
    for i in range(1, len(chunks), 2):
        pno = int(chunks[i]); body = chunks[i+1]
        mlow = re.search(r'^저신뢰:\s*(.*)$', body, flags=re.M)
        low = mlow.group(1).strip() if mlow else ""
        draft = []
        for ln in body.splitlines():
            s = ln.strip()
            if not s or s.startswith("저신뢰:"):
                continue
            if "자기 점검표" in s:
                break
            if re.search(r'[A-Za-z]', s) and not re.search(r'[가-힣]', s):
                draft.append(s)
        content = "[Google Vision literal 드래프트]\n" + "\n".join(draft)
        if low:
            content += "\n\n[Vision 저신뢰(<0.90) 단어: 시각 판독 표적]\n" + low
        open(os.path.join(out_dir, f"draft_p{pno:02d}.txt"), "w", encoding="utf-8").write(content)
        n += 1
    print(f"{n}개 드래프트 -> {out_dir}")

if __name__ == "__main__":
    main()
