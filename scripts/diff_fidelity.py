# -*- coding: utf-8 -*-
"""
diff_fidelity.py: 손글씨 충실 전사 파이프라인 ③단계: 검증 표적 자동 생성.

LLM 파서 출력(유창·환각/자동교정 위험)과 비-LLM OCR 출력(literal·confidence)을 토큰 정렬해
**발산 토큰**(LLM↔OCR 불일치 = 환각/교정/오독 후보)을 뽑고, OCR의 **저신뢰 단어**와 합쳐
페이지별 "육안 확인 표적" 목록을 만든다. 시각 판독을 전수 → 표적으로 좁히는 용도.

입력:
  <llm.md>   LlamaParse v2 등 LLM 파서 출력 (유창한 본문)
  <ocr.md>   gvision_parse.py 출력 (clean text + "저신뢰: word(0.NN), ..." 라인)
사용:
  python scripts/diff_fidelity.py <llm.md> <ocr.md> [--out targets.md] [--context 3]

페이지 페어링: OCR은 `## p.N` 헤더로, LLM은 `## p.N` 또는 반복 H1(`# 제목`)로 분할해 **순서(인덱스)로 페어링**
한다(1인 1페이지 합본 가정). 페이지 수가 다르면 경고 후 가능한 만큼만.
주의: 휴리스틱 타깃터다(정답 아님). OCR이 부정확하면 false-발산이 늘 수 있어 Vision 등 calibrated 엔진과
함께 쓴다. 최종 판정은 원본 이미지(육안).
"""
import sys, re, difflib

PAGE_RE = re.compile(r"^##\s*p\.?\s*0*(\d+)", re.M)   # "## p.1" / "## p01.png"
H1_RE = re.compile(r"^#\s+\S", re.M)                   # 반복 H1(예: llamaparse 페이지 제목)
LOW_RE = re.compile(r"저신뢰[:：]\s*(.+)")
LOW_ITEM_RE = re.compile(r"([^,(]+?)\(([0-9.]+)\)")
TOKEN_RE = re.compile(r"\S+")


def chunk_by(text, regex):
    """regex 매치 시작점마다 분할(헤더 라인 포함). 매치 없으면 [text]."""
    ms = list(regex.finditer(text))
    if not ms:
        return [text]
    return [text[ms[i].start():(ms[i + 1].start() if i + 1 < len(ms) else len(text))]
            for i in range(len(ms))]


def detect_llm_chunks(llm):
    """LLM 페이지 경계 자동 감지: '## p.N' 우선, 없으면 반복 H1, 그래도 없으면 통째."""
    for rgx in (PAGE_RE, H1_RE):
        ch = chunk_by(llm, rgx)
        if len(ch) >= 2:
            return ch
    return [llm]


def page_label(chunk, idx):
    m = PAGE_RE.search(chunk)
    return f"p.{m.group(1)}" if m else f"p.{idx + 1}"


def parse_low_conf(chunk):
    """청크에서 '저신뢰:' 추출 → [(word, conf)] + 헤딩/저신뢰 라인 제거한 본문."""
    low, body = [], []
    for line in chunk.splitlines():
        m = LOW_RE.search(line)
        if m:
            for w, c in LOW_ITEM_RE.findall(m.group(1)):
                low.append((w.strip(), float(c)))
        elif line.lstrip().startswith("#"):
            continue                      # 페이지 헤딩 제거
        else:
            body.append(line)
    return low, "\n".join(body)


def _strip_markup(s):
    """gvision 인라인 conf 주석(word⟨0.NN⟩)·HTML 태그(<u>,<br> 등) 제거 → 포맷 강건."""
    return re.sub(r"<[^>]*>", "", re.sub(r"⟨[^⟩]*⟩", "", s))


def norm(tok):
    return re.sub(r"^\W+|\W+$", "", _strip_markup(tok).lower())


def squash(seg):
    """발산 스킵 판정용: 주석·태그·공백·구두점 모두 제거한 '글자 시퀀스'. 같으면 노이즈."""
    return re.sub(r"[^0-9a-z가-힣]", "", _strip_markup("".join(seg)).lower())


def divergences(llm_text, ocr_text, context=3):
    a, b = TOKEN_RE.findall(llm_text), TOKEN_RE.findall(ocr_text)
    sm = difflib.SequenceMatcher(a=[norm(t) for t in a], b=[norm(t) for t in b], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        lseg = [t for t in a[i1:i2] if norm(t)]
        oseg = [t for t in b[j1:j2] if norm(t)]
        if not lseg and not oseg:
            continue                      # 순수 구두점 차이 스킵
        # 공백·구두점·토큰화만 다르고 글자는 같으면 노이즈 → 스킵
        # (예: "2026학년도 1학년" ↔ "2026 학년도 1 학년", "점(1가지 이상)" ↔ "점 1 가지 이상")
        if squash(lseg) == squash(oseg):
            continue
        ctx = " ".join(a[max(0, i1 - context):i1]) or " ".join(b[max(0, j1 - context):j1])
        out.append((tag, lseg, oseg, ctx))
    return out


def main():
    args, out_path, context, files = sys.argv[1:], None, 3, []
    i = 0
    while i < len(args):
        if args[i] == "--out":
            out_path = args[i + 1]; i += 2
        elif args[i] == "--context":
            context = int(args[i + 1]); i += 2
        else:
            files.append(args[i]); i += 1
    if len(files) < 2:
        print("사용: python diff_fidelity.py <llm.md> <ocr.md> [--out targets.md] [--context 3]")
        return
    llm = open(files[0], encoding="utf-8").read()
    ocr = open(files[1], encoding="utf-8").read()

    ocr_chunks = chunk_by(ocr, PAGE_RE)
    llm_chunks = detect_llm_chunks(llm)
    note = ""
    if len(ocr_chunks) != len(llm_chunks):
        note = f"\n> ⚠ 페이지 수 불일치 (LLM {len(llm_chunks)} · OCR {len(ocr_chunks)}), 앞에서부터 페어링.\n"
    n = min(len(ocr_chunks), len(llm_chunks))

    md = [f"# 검증 표적 (③ LLM↔OCR 발산 + OCR 저신뢰)\n",
          f"\n> LLM: `{files[0]}`  ↔  OCR: `{files[1]}`. 휴리스틱: 최종 판정은 원본 이미지.{note}\n"]
    tot_div = tot_low = 0
    for idx in range(n):
        low, ocr_body = parse_low_conf(ocr_chunks[idx])
        divs = divergences(llm_chunks[idx], ocr_body, context)
        tot_div += len(divs); tot_low += len(low)
        md.append(f"\n## {page_label(ocr_chunks[idx], idx)}  (발산 {len(divs)} · 저신뢰 {len(low)})\n")
        for tag, lseg, oseg, ctx in divs:
            l, o = " ".join(lseg) or "∅", " ".join(oseg) or "∅"
            md.append(f"- [{tag}] LLM:`{l}` ↔ OCR:`{o}`" + (f"  ⟨…{ctx}⟩" if ctx else ""))
        if low:
            md.append("- [저신뢰] " + ", ".join(f"{w}({c:.2f})" for w, c in low))
    md.append(f"\n\n---\n합계: 발산 {tot_div} · 저신뢰 {tot_low} (페어링 {n}페이지)\n")

    text = "\n".join(md)
    if out_path:
        open(out_path, "w", encoding="utf-8").write(text)
        print(f"검증 표적 작성: {out_path}  (발산 {tot_div} · 저신뢰 {tot_low}, {n}페이지)")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
