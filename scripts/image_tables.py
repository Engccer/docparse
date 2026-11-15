"""PDF에 이미지로 박힌 표의 격자를 세고, 표마다 판독용 확대 조각을 만든다.

  python image_tables.py <파일.pdf> --out <폴더> [--pages 4,25-27] [--max-width 2000]
                         [--band-rows 6] [--min-share 0.05] [--header-rows N] [--header-rows p025.g00=5 ...]

대상: 글자층에는 제목만 있고 수치표는 저해상도 이미지로 박힌 PDF(카탈로그·스캔 부록 등).
여러 판독기(비전 모델·OCR)에 나눠 읽히기 전에 두 가지를 준비한다.
  1) 쪽마다 원본 이미지에 표 격자가 몇 개 있는지 센다. 파서가 낸 표 개수와 쪽별로 견주면
     파서가 표를 통째로 빠뜨린 쪽이 드러난다.
  2) 격자마다 전체 조각(overview), 머리글 띠(header), 행 띠(bNN)를 확대해 저장하고
     위치를 manifest.json에 적는다.

이 스크립트는 값을 읽지 않는다. 위치와 조각만 만들며 숫자 값을 보증하지 않는다.

픽셀을 얻는 방법: 이미지를 xref에서 직접 꺼내지 않고 쪽을 렌더한다(CMYK·Separation JPEG를 직접
꺼내면 색이 반전되는 경우가 있었다). 가로·세로 배율을 원본 화소 수 / bbox 크기로 따로 잡고 bbox 왼쪽
위가 화소 원점에 오게 옮겨, 원본 화소와 1:1로 맞는 픽셀을 얻는다(rendered_px = native_px). 균일
배율로 렌더하면 bbox가 화소 사이에 걸려 반 화소 어긋나게 다시 보간되어 흐려진다.
겹친 이미지(전면 배경 위 표 이미지 등)에서 쪽 위 자리가 80% 이상 겹치는 격자는 더 작은 이미지의
것 하나만 남긴다. 쪽 면적의 --min-share보다 작은 이미지는 건너뛰되 그 수를 적고, 맞닿은 작은
이미지들이 큰 영역을 이루면(표를 띠 이미지로 쪼개 넣은 PDF) 경고한다.

확대: Pillow Lanczos 보간만 쓴다. 생성형 초해상은 숫자를 지어낼 수 있어 쓰지 않는다.
배율은 min(4, max_width / 조각 너비)이고 1보다 작게 줄이지 않는다.

격자 검출(numpy 없이 순수 파이썬 + Pillow C 연산):
  - 주변 평균보다 뚜렷이 어둡거나 아주 어두운 화소를 잉크로 이진화한다(적응형 문턱이라 옅은 바탕색·
    줄무늬 음영에 강하고, 절대 문턱이 짙게 채운 띠의 안쪽까지 잡는다).
  - 한 줄을 bytes로 보고 정규식으로 긴 연속 구간을 찾아 가로 선분을 얻는다(C 수준 탐색이라 빠름).
    한 화소 끊김은 오른쪽으로 한 칸 민 사본과 OR해 메운다. 세로선은 이미지를 전치해 같은 방법으로 찾는다.
  - 이웃한 줄의 선분을 이어 두께 있는 선으로 만든다. 얇으면 선, 'CLASS 900'·흰 글자 머리글 같은
    짙게 채운 면이 두께의 4배 이상 길면 두께와 상관없이 띠(위아래 가장자리를 경계선으로 친다)로 본다.
    세로선은 가로 띠를 지운 뒤 찾는다.
  - 가로선과 세로선이 만나면(약 6pt 여유) union-find로 한 묶음으로 친다. 가로·세로 경계선이 각각
    4개 이상이고, 묶음 너비를 거의 다 가로지르는 가로 경계선 2개 이상·높이 대부분을 내려가는 세로
    경계선 2개 이상이 있는 묶음만 표로 본다. 이미지 너비의 절반이 안 되는 묶음은 같은 간격 행이
    4개 이상(전체 행의 40% 이상) 이어질 때만 표로 본다(도면의 단면·치수선 제외).

행 띠:
  - 행 경계선 간격(행 수)이 글자 줄 간격과 비슷하면(rows 모드) 띠 하나가 --band-rows개 행 간격을
    덮고 위아래로 1행씩 겹친다.
  - 행 경계선이 글자 여러 줄마다 하나뿐이거나(예: 3행 묶음마다 괘선) 경계선을 충분히 찾지 못하면
    (fixed 모드) 글자 줄 간격 x --band-rows 높이의 띠로 자른다. 자르는 자리는 글자가 없는 높이로
    맞추되 창 안에 행 경계선이 있으면 그 선에서 자르고, 이웃 띠와 글자 한 줄씩 통째로 겹친다. 이때
    row_from·row_to는 null이다. 첫 띠 위와 마지막 띠 아래는 두 모드 모두 격자 끝까지다.
  - 머리글: 본문 단위 행 높이의 정수배 간격이 맨 아래까지 이어지기 시작하는 전폭 경계선을 본문 시작으로
    보고(괘선이 빠지면 본문 간격이 2배·3배로 보이므로), 격자 위쪽부터 거기까지를 머리글 띠로 저장한다.
    둘째 띠부터는 머리글 띠를 빨간 구분 막대와 함께 띠 위에 붙여 띠 하나만 봐도 열 뜻을 알 수 있게
    한다. 추정에 실패하면 머리글 띠를 만들지 않는다. --header-rows N은 모든 격자에, --header-rows
    p025.g00=5는 그 격자에만 직접 준다(여러 번 줄 수 있다).

같은 --out 폴더에 다시 돌리면 처리하는 쪽의 pNNN.*.png를 먼저 지우고, 기존 manifest.json에서 그 쪽만
갈아 끼운 뒤 summary를 다시 센다. 다른 문서의 매니페스트가 있던 폴더면 경고하고 새로 쓴다.

종료 코드: 0 = 정상(격자가 하나도 없어도 0), 1 = 입력 오류.
알려진 한계: 이미지를 거의 꽉 채운 도면처럼 긴 직선이 서로 만나는 그림은 격자로 잡힐 수 있다. 머리글
추정은 자료 행 몇 줄을 머리글에 넣거나 못 정할 수 있다(header_source가 estimated). 쪽별 격자 수를 파서
표 수와 견줄 때와 조각을 판독기에 넘기기 전에 overview·header 조각을 열어 확인한다.
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

MAX_SCALE = 4
LOW_DPI = 150
PAD = 3  # 조각 가장자리 여유(원본 픽셀). 바깥 테두리 선이 잘리지 않게 한다.
ADAPTIVE_RADIUS = 7  # 적응형 문턱의 주변 평균 창(15x15)
ADAPTIVE_OFFSET = 20  # 주변 평균보다 이만큼 어두워야 잉크로 본다(JPEG 잡음·옅은 음영 제외)
DARK = 110  # 이보다 어두우면 주변과 상관없이 잉크(짙게 채운 띠의 안쪽까지 잉크로 잡는다)
GAP = 1  # 선분 안의 끊김을 이만큼(화소) 메운다
JOIN_PT = 6  # 가로선·세로선이 만난다고 볼 여유(pt). 짙은 띠와 본문 사이 흰 틈(실측 4~8px@100DPI)을 넘는다
SEPARATOR = 6  # 붙인 머리글과 띠 사이 빨간 구분 막대 높이(px). 머리글 행을 띠의 자료 행으로 다시 읽지 않게 한다
SEPARATOR_RGB = (220, 0, 0)
NOTICE = ("이 매니페스트는 이미지 속 표 격자의 위치와 확대 조각만 담는다. 숫자 값을 읽지 않았으며 "
          "숫자 값을 보증하지 않는다. 조각은 Lanczos 보간 확대일 뿐 원본 해상도를 넘는 정보는 없다.")
ROW_NOTE = ("row_from·row_to는 0부터 세는 행 간격 번호이며 둘 다 포함한다. fixed 모드 띠에서는 null이다. "
            "header_attached가 true인 띠는 맨 위에 머리글 띠를 붙이고 빨간 막대로 나눴다. 막대 위는 열 뜻을 "
            "알리는 참고용이므로 그 띠의 자료로 다시 옮겨 적지 않는다. header_source가 estimated면 머리글 경계는 "
            "추정이라 자료 행이 섞일 수 있다. 띠 맨 위·맨 아래에 반쯤 잘린 줄이 보이면 옮기지 않는다"
            "(이웃 띠에 온전히 들어 있다).")


def _fitz():
    try:
        import pymupdf
    except ImportError:  # 구버전은 fitz만 있다
        import fitz as pymupdf
    return pymupdf


# ---------- 입력 해석 ----------

def parse_pages(spec, page_count):
    """'4,25-27' → [4, 25, 26, 27] (1부터, 중복 제거·정렬). 잘못된 값은 ValueError."""
    pages = set()
    if not spec or not spec.strip():
        raise ValueError("쪽 지정이 비어 있다")
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"쪽 지정을 해석할 수 없다: {part!r}")
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if a < 1 or b < a or b > page_count:
            raise ValueError(f"쪽 범위가 문서(1~{page_count}쪽)를 벗어나거나 거꾸로다: {part!r}")
        pages.update(range(a, b + 1))
    return sorted(pages)


# ---------- 이진화·선 검출 ----------

def binarize(img):
    """주변 평균보다 ADAPTIVE_OFFSET 이상 어둡거나 DARK보다 어두운 화소를 255, 나머지를 0으로 둔 L 이미지.

    적응형 문턱만 쓰면 짙게 채운 띠는 가장자리만 잉크가 되어 띠로 알아보지 못한다.
    """
    gray = img.convert("L")
    local = gray.filter(ImageFilter.BoxBlur(ADAPTIVE_RADIUS))
    diff = ImageChops.subtract(local, gray)  # 주변보다 어두운 만큼(밝으면 0)
    adaptive = diff.point(lambda v: 255 if v >= ADAPTIVE_OFFSET else 0)
    return ImageChops.lighter(adaptive, gray.point(lambda v: 255 if v < DARK else 0))


def _shift_right(img, s):
    out = Image.new("L", img.size, 0)
    out.paste(img.crop((0, 0, img.width - s, img.height)), (s, 0))
    return out


def _segments(bw, min_len):
    """각 줄에서 길이 min_len 이상인 잉크 연속 구간 [(y, x0, x1)] (x1 포함). GAP 화소 끊김은 잇는다."""
    dil = bw
    for s in range(1, GAP + 1):
        dil = ImageChops.lighter(dil, _shift_right(bw, s))
    w, h = dil.size
    data = dil.tobytes()
    pat = re.compile(rb"\xff{%d,}" % min_len)
    segs = []
    for y in range(h):
        base = y * w
        for m in pat.finditer(data, base, base + w):
            segs.append((y, m.start() - base, m.end() - base - 1 - GAP))
    return segs


def _merge_segments(segs):
    """이웃한 줄의 겹치는 선분을 한 선으로 잇는다. 같은 줄에서 글자 구멍으로 끊긴 조각도 합친다."""
    lines = []  # [a0, a1, b0, b1]: a = 선의 두께 방향(줄 번호), b = 길이 방향
    open_lines = []
    for y, x0, x1 in segs:
        open_lines = [ln for ln in open_lines if ln[1] >= y - 1]
        for ln in open_lines:
            if ln[1] >= y - 1 and min(ln[3], x1) - max(ln[2], x0) >= 0.5 * min(ln[3] - ln[2], x1 - x0):
                ln[1] = y
                ln[2] = min(ln[2], x0)
                ln[3] = max(ln[3], x1)
                break
        else:
            ln = [y, y, x0, x1]
            lines.append(ln)
            open_lines.append(ln)
    return lines


def _classify(lines, max_thick, bar_min_len):
    """두께로 가른다: max_thick 이하 = 선, 더 두껍고 두께의 4배·bar_min_len 이상 길면 = 띠(bar), 그 밖 = 버림.

    띠는 'CLASS 900'·흰 글자 머리글처럼 짙게 채운 가로 면이다. 두께 상한은 두지 않는다. 버리면 띠 위아래
    세로선이 끊겨 표가 갈라지거나, 띠가 세로로 보면 굵은 '세로선'이 되어 진짜 세로선을 삼키고 함께
    버려져 표 전체가 사라진다(실측: 30px 이상 짙은 머리글). 띠는 묶음을 잇는 데 쓰고 위아래(또는 좌우)
    가장자리를 경계선으로 친다.
    """
    out = []
    for a0, a1, b0, b1 in lines:
        thick, length = a1 - a0 + 1, b1 - b0 + 1
        if thick <= max_thick:
            out.append((a0, a1, b0, b1, False))
        elif length >= max(4 * thick, bar_min_len):
            out.append((a0, a1, b0, b1, True))
    return out


def find_lines(bw, dpi):
    """이진 이미지에서 긴 가로선·세로선. 가로 dict(y0,y1,x0,x1,bar), 세로 dict(x0,x1,y0,y1,bar)."""
    w, h = bw.size
    max_thick = max(5, round(dpi / 72 * 4))
    h_min = max(24, w // 25)
    v_min = max(20, h // 40)
    hs = [dict(y0=a0, y1=a1, x0=b0, x1=b1, bar=bar)
          for a0, a1, b0, b1, bar in _classify(_merge_segments(_segments(bw, h_min)), max_thick, w // 4)]
    # 가로 띠 안의 세로 잉크(띠 속 흰 글자 사이 기둥)가 열 경계선으로 잡히지 않게 띠를 지우고 세로선을 찾는다
    bars = [l for l in hs if l["bar"]]
    if bars:
        mask = Image.new("L", bw.size, 0)
        draw = ImageDraw.Draw(mask)
        for l in bars:
            draw.rectangle([l["x0"], l["y0"], l["x1"], l["y1"]], fill=255)
        bw = ImageChops.subtract(bw, mask)
    bt = bw.transpose(Image.Transpose.TRANSPOSE)
    vs = [dict(x0=a0, x1=a1, y0=b0, y1=b1, bar=bar)
          for a0, a1, b0, b1, bar in _classify(_merge_segments(_segments(bt, v_min)), max_thick, h // 4)]
    return hs, vs


def _edges(lines, lo, hi):
    """선은 가운데 한 위치, 띠는 양쪽 가장자리 두 위치."""
    out = []
    for l in lines:
        out.extend([l[lo], l[hi]] if l["bar"] else [(l[lo] + l[hi]) / 2])
    return out


def longest_equal_run(positions):
    """거의 같은 간격(±15%, 최소 2px)이 이어지는 가장 긴 구간 (시작 번호, 길이)."""
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    best_start, best_len = 0, 0
    for i, ref in enumerate(gaps):
        j = i
        while j + 1 < len(gaps) and abs(gaps[j + 1] - ref) <= max(2.0, 0.15 * ref):
            j += 1
        if j - i + 1 > best_len:
            best_start, best_len = i, j - i + 1
    return best_start, best_len


def _cluster(values, tol):
    """정렬한 위치를 tol 이내끼리 묶어 평균(소수 첫째 자리)."""
    groups = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [round(sum(g) / len(g), 1) for g in groups]


def _long_tracks(lines, a0, a1, b0, b1, need, tol):
    """같은 위치(tol 이내)에 놓인 선 조각들의 길이 합이 need 이상인 위치 수.

    띠나 병합 칸에 끊긴 한 경계선을 조각별이 아니라 한 줄로 잰다.
    """
    tracks = []  # [위치, 길이 합]
    for l in sorted(lines, key=lambda l: (l[a0] + l[a1]) / 2):
        pos, length = (l[a0] + l[a1]) / 2, l[b1] - l[b0] + 1
        if tracks and pos - tracks[-1][0] <= tol:
            tracks[-1][1] += length
        else:
            tracks.append([pos, length])
    return sum(t[1] >= need for t in tracks)


def _row_positions(gh, gv, gw, tol, bw, gray):
    """행 경계선 위치. 칸 안의 가로 획('-' 표시, 숫자 밑변, 밑줄)은 뺀다.

    같은 높이(tol 이내) 조각들을 한 줄로 보고 다음 중 하나일 때만 경계선으로 친다.
      - 짙은 띠의 가장자리.
      - 이어진 길이가 격자 너비의 50% 이상이다. 조각 사이 틈이 회색으로 이어져 있으면(틈 화소의 70% 이상이
        위아래 종이보다 어둡다) 한 줄로 잰다. 세로선 조건은 두지 않는다: 진한 가로선 가까이에서는 옅은 세로선의
        이진화가 끊겨 그 높이에 세로선이 없을 수 있다(실측). 좁은 칸마다 놓인 대시 행은 칸 경계마다 흰 틈이
        있어 한 줄로 이어지지 않는다.
      - 길이 합이 격자 너비의 25% 이상이고 조각 하나라도 세로선에 이어진다.
      - 조각 하나가 양 끝 모두 세로선에 이어지고(병합 머리글 아래 짧은 선) 위아래 2~3px에 글자 잉크가 없다.
    '이어진다'는 조각 끝이 세로선에 닿거나, 세로선까지 남은 틈(12px 이내)이 위아래 종이보다 어둡다는 뜻이다.
    옅은 괘선은 세로선 가까이(적응형 문턱 창 반경 안)에서 이진화가 끊기지만 회색으로는 이어져 있고, 칸 안의
    대시는 세로선 앞에 흰 틈이 있다. 좁은 열을 꽉 채운 숫자 밑변은 세로선에 닿아도 바로 위에 글자 잉크가
    있다. 원본 화소에 맞춰 선명하게 렌더하면 이런 획도 선 문턱을 넘으므로 필요하다(실측).
    """
    def verticals_at(l):
        return [v for v in gv if v["y0"] - 1 <= l["y1"] and v["y1"] + 1 >= l["y0"]]

    def darker_gap(l, gx0, gx1):
        if gx1 < gx0:
            return True
        line = gray.crop((gx0, l["y0"], gx1 + 1, l["y1"] + 1)).tobytes()
        refs = [gray.crop((gx0, y, gx1 + 1, y + 1)).tobytes()
                for y in (l["y0"] - 3, l["y1"] + 3) if 0 <= y < gray.height]
        if not refs:
            return False
        paper = min(sum(r) / len(r) for r in refs)
        return paper - sum(line) / len(line) >= 8

    def connected(l, x, side):
        """조각 끝 x(side -1 = 왼쪽 끝, +1 = 오른쪽 끝)가 세로선에 이어지는가."""
        best = None
        for v in verticals_at(l):
            if v["x0"] - 2 <= x <= v["x1"] + 2:
                return True
            gap = v["x0"] - x - 1 if side > 0 else x - v["x1"] - 1
            if 0 < gap <= 12 and (best is None or gap < best[0]):
                best = (gap, v)
        if best is None:
            return False
        v = best[1]
        return darker_gap(l, x + 1, v["x0"] - 1) if side > 0 else darker_gap(l, v["x1"] + 1, x - 1)

    def gap_continuous(y0, y1, gx0, gx1):
        """두 조각 사이 틈(gx0~gx1)이 회색으로 이어져 있는가: 틈 화소의 70% 이상이 위아래 종이보다 8 이상 어둡다."""
        if gx1 < gx0:
            return True
        w = gx1 - gx0 + 1
        rows = [gray.crop((gx0, y, gx1 + 1, y + 1)).tobytes() for y in range(y0, y1 + 1)]
        line = [min(r[i] for r in rows) for i in range(w)]
        refs = [gray.crop((gx0, y, gx1 + 1, y + 1)).tobytes() for y in (y0 - 3, y1 + 3) if 0 <= y < gray.height]
        if not refs:
            return False
        paper = [max(r[i] for r in refs) for i in range(w)]
        return sum(p - v >= 8 for p, v in zip(paper, line)) >= 0.7 * w

    def longest_run(lines):
        """조각들을 회색으로 이어진 틈까지 이어 붙인 가장 긴 길이."""
        best = run = 0
        prev = None
        for l in sorted(lines, key=lambda l: l["x0"]):
            if prev is not None and l["x0"] <= prev["x1"] + 1:
                run += max(0, l["x1"] - prev["x1"])
            elif prev is not None and gap_continuous(min(l["y0"], prev["y0"]), max(l["y1"], prev["y1"]),
                                                    prev["x1"] + 1, l["x0"] - 1):
                run += l["x1"] - prev["x1"]
            else:
                run = l["x1"] - l["x0"] + 1
            best = max(best, run)
            if prev is None or l["x1"] > prev["x1"]:
                prev = l
        return best

    def crosses(l):
        return any(l["x0"] < v["x0"] and v["x1"] < l["x1"] for v in verticals_at(l))

    def text_adjacent(l):
        x0, x1 = l["x0"] + 3, l["x1"] - 2
        w = x1 - x0
        if w < 4:
            return False
        # 바로 붙은 한 줄은 굵은 선의 번짐일 수 있어 2~3px 떨어진 두 줄을 본다
        for top in (l["y0"] - 3, l["y1"] + 2):
            if top < 0 or top + 2 > bw.height:
                continue
            band = bw.crop((x0, top, x1, top + 2)).tobytes()
            if max(band[:w].count(255), band[w:].count(255)) > 0.15 * w:
                return True
        return False

    def short_rule(l):
        return connected(l, l["x0"], -1) and connected(l, l["x1"], 1) and not text_adjacent(l)

    groups = []  # [위치들, 길이 합, 조각들, 띠인가, 마지막 높이]
    for l in sorted(gh, key=lambda l: (l["y0"] + l["y1"]) / 2):
        mid = (l["y0"] + l["y1"]) / 2
        if groups and not l["bar"] and not groups[-1][3] and mid - groups[-1][4] <= tol:
            g = groups[-1]
            g[0].extend(_edges([l], "y0", "y1"))
            g[1] += l["x1"] - l["x0"] + 1
            g[2].append(l)
            g[4] = mid
        else:
            groups.append([_edges([l], "y0", "y1"), l["x1"] - l["x0"] + 1, [l], l["bar"], mid])
    keep = []
    for pos, length, lines, bar, _ in groups:
        if (bar or (length >= 0.5 * gw and longest_run(lines) >= 0.5 * gw) or (length >= 0.25 * gw and any(crosses(l) or connected(l, l["x0"], -1)
                                                 or connected(l, l["x1"], 1) for l in lines))
                or any(short_rule(l) for l in lines)):
            keep.extend(pos)
    return _cluster(keep, tol)


def detect_grids(img, dpi=100):
    """PIL 이미지에서 표 격자 목록. 각 항목: bbox_px, row_lines_px, col_lines_px, rows, cols, h_lines, v_lines.

    위에서 아래로(같은 높이대면 왼쪽부터) 정렬한다.
    """
    bw = binarize(img)
    gray = img.convert("L")
    hs, vs = find_lines(bw, dpi)
    parent = list(range(len(hs) + len(vs)))
    join = max(3, round(dpi / 72 * JOIN_PT))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, hl in enumerate(hs):
        for j, vl in enumerate(vs):
            if (vl["x1"] >= hl["x0"] - join and vl["x0"] <= hl["x1"] + join
                    and hl["y1"] >= vl["y0"] - join and hl["y0"] <= vl["y1"] + join):
                a, b = find(i), find(len(hs) + j)
                if a != b:
                    parent[a] = b
    groups = {}
    for i in range(len(hs) + len(vs)):
        groups.setdefault(find(i), []).append(i)

    tol = max(3, round(dpi / 72 * 2))
    grids = []
    for members in groups.values():
        gh = [hs[i] for i in members if i < len(hs)]
        gv = [vs[i - len(hs)] for i in members if i >= len(hs)]
        if len(gh) < 4 or len(gv) < 2:  # 세로선 4개 조건은 양옆 테두리를 보탠 뒤 경계선 수로 따진다
            continue
        x0 = min(min(l["x0"] for l in gh), min(l["x0"] for l in gv))
        x1 = max(max(l["x1"] for l in gh), max(l["x1"] for l in gv))
        y0 = min(min(l["y0"] for l in gh), min(l["y0"] for l in gv))
        y1 = max(max(l["y1"] for l in gh), max(l["y1"] for l in gv))
        gw, ghh = x1 - x0 + 1, y1 - y0 + 1
        if gw < 40 or ghh < 30:
            continue
        if _long_tracks(gh, "y0", "y1", "x0", "x1", 0.8 * gw, tol) < 2:
            continue
        if _long_tracks(gv, "x0", "x1", "y0", "y1", 0.6 * ghh, tol) < 2:
            continue
        cols_px = _cluster(_edges(gv, "x0", "x1"), tol)
        rows_px = _row_positions(gh, gv, gw, tol, bw, gray)
        # 양옆(또는 위아래) 테두리 없이 열린 표: 긴 가로선의 양 끝을 왼쪽·오른쪽 경계로 친다
        long_h = [l for l in gh if l["x1"] - l["x0"] + 1 >= 0.8 * gw]
        long_v = [l for l in gv if l["y1"] - l["y0"] + 1 >= 0.6 * ghh]
        edge_tol = max(tol, 0.02 * gw)
        for e in ([min(l["x0"] for l in long_h), max(l["x1"] for l in long_h)] if long_h else []):
            if all(abs(e - c) > edge_tol for c in cols_px):
                cols_px = sorted(cols_px + [float(e)])
        edge_tol = max(tol, 0.02 * ghh)
        for e in ([min(l["y0"] for l in long_v), max(l["y1"] for l in long_v)] if long_v else []):
            if all(abs(e - r) > edge_tol for r in rows_px):
                rows_px = sorted(rows_px + [float(e)])
        if len(rows_px) < 4 or len(cols_px) < 4:
            continue
        # 이미지 너비의 절반이 안 되는 작은 묶음은 도면(치수선·단면)일 때가 많다. 다음 중 하나일 때만 표로 친다.
        #  - 같은 간격의 행이 4개 이상, 전체 행의 40% 이상 이어진다(작은 정형 표)
        #  - 이미지 너비의 40% 이상이고 높이를 거의(90%) 다 내려가는 세로 경계선이 2개 이상이다
        #    (행 높이가 제각각인 반쪽 폭 표. 도면의 세로선은 묶음 높이를 끝까지 내려가는 일이 드물다)
        if gw < 0.5 * img.width:
            regular = longest_equal_run(rows_px)[1] >= max(4, 0.4 * (len(rows_px) - 1))
            columnar = gw >= 0.4 * img.width and _long_tracks(gv, "x0", "x1", "y0", "y1", 0.9 * ghh, tol) >= 2
            if not (regular or columnar):
                continue
        full = [i for i, r in enumerate(rows_px)
                if sum(l["x1"] - l["x0"] + 1 for l in gh
                       if min(abs(e - r) for e in _edges([l], "y0", "y1")) <= tol) >= 0.9 * gw]
        grids.append(dict(bbox_px=[x0, y0, x1 + 1, y1 + 1], row_lines_px=rows_px, col_lines_px=cols_px,
                          rows=len(rows_px) - 1, cols=len(cols_px) - 1, h_lines=gh, v_lines=gv,
                          full_row_lines=full))
    band = max(1.0, 0.05 * img.height)
    grids.sort(key=lambda g: (round(g["bbox_px"][1] / band), g["bbox_px"][0]))
    if grids:
        _attach_profiles(bw, grids)
    return grids


# ---------- 머리글·글자 줄 추정 ----------

def _multiple(gap, unit):
    """gap이 unit의 정수배(1~6배, 배수 오차 0.12 이내)이면 그 배수, 아니면 0."""
    k = round(gap / unit)
    return k if 1 <= k <= 6 and abs(gap / unit - k) <= 0.12 else 0


def estimate_header_rows(row_lines, full_lines=None):
    """본문이 시작하는 행 번호(= 머리글 행 수). 못 정하면 None.

    본문 단위 행 높이: 그 정수배로 설명되는 간격의 높이 합이 가장 큰 간격 값. 괘선이 군데군데
    빠지면 본문 간격이 2배·3배로 나타나므로 '같은 간격'이 아니라 '단위의 정수배'로 본다.
    맨 아래 간격(덜 찬 마지막 묶음)은 빼고, 아래에서부터 정수배가 끊기지 않는 곳까지를 본문으로 친다.
    머리글 행이 마침 본문 행의 2배 높이 같은 정수배여도, 바로 뒤에 1배 간격이 3개 이어지면 그 앞까지를
    머리글로 돌린다. full_lines(격자 너비를 거의 다 가로지르는 경계선 번호)를 주면 머리글 경계를 그런
    선으로 맞춘다. 머리글 안의 선은 병합 칸 때문에 짧고, 머리글 끝 행이 마침 본문 행 높이와 같으면
    그 짧은 선에서 머리글이 끊기기 때문이다(실측). 본문 간격이 3개 미만, 시작이 0, 머리글이 격자 높이의
    35% 초과면 None.
    """
    gaps = [b - a for a, b in zip(row_lines, row_lines[1:])]
    n = len(gaps)
    if n < 4:
        return None
    unit = max((g for g in gaps if g >= 3),
               key=lambda u: (sum(g for g in gaps if _multiple(g, u)), u), default=None)
    if unit is None:
        return None
    ks = [_multiple(g, unit) for g in gaps]
    start = n - 1
    while start > 0 and ks[start - 1]:
        start -= 1
    first_single_run = next((m for m in range(start, n - 2) if ks[m] == ks[m + 1] == ks[m + 2] == 1), None)
    if first_single_run is not None and first_single_run - start <= 3 and all(k >= 2 for k in ks[start:first_single_run]):
        start = first_single_run
    if full_lines is not None and start:
        while start < n and start not in full_lines:
            start += 1
    if start == 0 or n - start < 3:
        return None
    total = row_lines[-1] - row_lines[0]
    if total <= 0 or row_lines[start] - row_lines[0] > 0.35 * total:
        return None
    return start


def _attach_profiles(bw, grids):
    """격자마다 선을 지운 잉크의 높이별 개수(ink_profile, 격자 위쪽부터)를 붙인다."""
    mask = Image.new("L", bw.size, 0)
    d = ImageDraw.Draw(mask)
    for g in grids:
        for l in g["h_lines"] + g["v_lines"]:
            d.rectangle([l["x0"] - 1, l["y0"] - 1, l["x1"] + 1, l["y1"] + 1], fill=255)
    ink = ImageChops.subtract(bw, mask)
    for g in grids:
        x0, y0, x1, y1 = g["bbox_px"]
        part = ink.crop((x0 + 2, y0, max(x0 + 3, x1 - 2), y1))
        w = part.width
        data = part.tobytes()
        g["ink_profile"] = [data[i * w:(i + 1) * w].count(255) for i in range(part.height)]


def estimate_text_pitch(profile, width):
    """잉크 높이 분포에서 글자 줄 간격(화소). 줄이 3개 미만이면 None."""
    thr = max(3, 0.02 * width)
    centers = []
    start = None
    for y, c in enumerate(list(profile) + [0]):
        if c > thr and start is None:
            start = y
        elif c <= thr and start is not None:
            if y - start >= 2:
                centers.append((start + y - 1) / 2)
            start = None
    if len(centers) < 3:
        return None
    return statistics.median(b - a for a, b in zip(centers, centers[1:]))


# ---------- 띠 계획 ----------

def plan_bands(grid, band_rows, header_rows):
    """(header_rows, band_mode, bands[{row_from,row_to,y0,y1}]). y는 이미지 픽셀."""
    rl = grid["row_lines_px"]
    rows = len(rl) - 1
    gy0, gy1 = grid["bbox_px"][1], grid["bbox_px"][3]
    if header_rows is not None:
        hr = min(header_rows, rows - 1) or None
    else:
        hr = estimate_header_rows(rl, grid.get("full_row_lines"))
    h = hr or 0
    body_top = rl[h] if hr else gy0
    gw = grid["bbox_px"][2] - grid["bbox_px"][0]
    prof = grid.get("ink_profile") or []
    off = gy0
    pitch = estimate_text_pitch(prof[int(body_top - off):], gw) if prof else None
    body_gaps = [b - a for a, b in zip(rl[h:], rl[h + 1:])]
    # 글자 1.6줄보다 높은 행 간격이 본문 높이의 절반 이상이면 경계선이 성기다(여러 줄마다 괘선 하나)
    # 줄 간격을 모르면(글자 줄 3개 미만) 행 경계선을 그대로 믿는다(rows 모드)
    sparse = (pitch is not None and bool(body_gaps)
              and sum(gp for gp in body_gaps if gp > 1.6 * pitch) >= 0.5 * sum(body_gaps))

    bands = []
    if not sparse:
        k = 0
        while True:
            core0 = h + k * band_rows
            if core0 >= rows:
                break
            core1 = min(rows, core0 + band_rows)  # 제외 경계
            r_from = 0 if k == 0 else core0 - 1
            r_to = min(rows - 1, core1)
            bands.append(dict(row_from=r_from, row_to=r_to, y0=rl[r_from], y1=rl[r_to + 1]))
            k += 1
        # 첫·마지막 경계선 바깥에 남은 행(위·아래 테두리 없는 표)도 띠에 들어가게 격자 끝까지 넓힌다
        bands[0]["y0"] = min(bands[0]["y0"], gy0)
        bands[-1]["y1"] = max(bands[-1]["y1"], gy1)
        return hr, "rows", bands

    # fixed 모드: 글자 줄 간격 x band_rows 높이. 자르는 자리는 창 안에 행 경계선이 있으면 그 선, 없으면
    # 잉크가 가장 적은 높이. 창을 줄 간격의 ±0.55로 잡아 글자 사이 빈 높이가 늘 창 안에 들게 한다.
    height = pitch * band_rows
    win = 0.55 * pitch

    def snap(target):
        lo, hi = target - win, target + win
        on_line = [r for r in rl if lo <= r <= hi and gy0 < r < gy1]
        if on_line:
            return min(on_line, key=lambda r: abs(r - target))
        cand = [y for y in range(int(lo), int(hi) + 1) if 0 <= y - off < len(prof)]
        return min(cand, key=lambda y: (prof[y - off], abs(y - target))) if cand else target

    cuts = [body_top]
    while True:
        target = cuts[-1] + height
        if gy1 - target < 0.3 * height:
            cuts.append(gy1)
            break
        cuts.append(snap(target))
    for i, (a, b) in enumerate(zip(cuts, cuts[1:])):
        # 겹침: 글자 한 줄씩 통째로(빈 높이나 경계선에 맞춰) 겹친다. 고정 비율로 넓히면 겹친 줄이
        # 반쯤 잘려 숫자를 잘못 읽게 된다(실측).
        top = gy0 if i == 0 else max(gy0, snap(a - pitch))
        bottom = gy1 if b >= gy1 else min(gy1, snap(b + pitch))
        bands.append(dict(row_from=None, row_to=None, y0=top, y1=bottom))
    return hr, "fixed", bands


# ---------- 조각 저장 ----------

def _crop(img, box):
    x0, y0, x1, y1 = box
    return img.crop((int(x0), int(y0), int(round(x1)), int(round(y1))))


def _scaled(img, scale):
    if scale == 1:
        return img
    size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    return img.resize(size, Image.Resampling.LANCZOS)


def save_grid_crops(img, grid, gid, out, max_width, band_rows, header_rows):
    """overview·header·bNN 조각을 저장하고 매니페스트용 필드를 돌려준다."""
    W, H = img.size
    x0, y0, x1, y1 = grid["bbox_px"]
    cx0, cx1 = max(0, x0 - PAD), min(W, x1 + PAD)
    clamp_y = lambda y: min(H, max(0, y))  # noqa: E731
    crop_w = cx1 - cx0
    scale = min(MAX_SCALE, max_width / crop_w)
    scale = round(max(1.0, scale), 4)
    # int() 내림으로 저장하므로 반올림한 배율이 조금 커도 너비는 max_width를 넘지 않게 다시 맞춘다
    while scale > 1 and int(crop_w * scale) > max_width:
        scale = round(scale - 0.0001, 4)

    overview = f"{gid}.overview.png"
    _scaled(_crop(img, (cx0, clamp_y(y0 - PAD), cx1, clamp_y(y1 + PAD))), scale).save(out / overview)

    hr, mode, plan = plan_bands(grid, band_rows, header_rows)
    header_file, header_img = None, None
    if hr:
        hy1 = grid["row_lines_px"][hr]
        header_img = _scaled(_crop(img, (cx0, clamp_y(y0 - PAD), cx1, clamp_y(hy1 + PAD))), scale)
        header_file = f"{gid}.header.png"
        header_img.save(out / header_file)

    bands = []
    for k, b in enumerate(plan):
        # 격자 바깥 테두리에서만 PAD만큼 넓힌다. 안쪽 자르는 자리에서 넓히면 이웃 줄 글자 끝이 비친다
        top_pad = PAD if b["y0"] <= y0 else 1
        bottom_pad = PAD if b["y1"] >= y1 else 1
        box = [cx0, clamp_y(b["y0"] - top_pad), cx1, clamp_y(b["y1"] + bottom_pad)]
        piece = _scaled(_crop(img, box), scale)
        if header_img is not None and k > 0:
            joined = Image.new("RGB", (piece.width, header_img.height + SEPARATOR + piece.height), SEPARATOR_RGB)
            joined.paste(header_img, (0, 0))
            joined.paste(piece, (0, header_img.height + SEPARATOR))
            piece = joined
        name = f"{gid}.b{k:02d}.png"
        piece.save(out / name)
        bands.append(dict(file=name, row_from=b["row_from"], row_to=b["row_to"],
                          bbox_px=[round(v, 1) for v in box], header_attached=header_img is not None and k > 0))
    source = None if hr is None else ("given" if header_rows is not None else "estimated")
    return dict(scale=scale, overview=overview, header=header_file, header_rows=hr, header_source=source,
                band_mode=mode, bands=bands)


# ---------- 쪽 처리 ----------

def page_images(page, fitz, min_share):
    """(다룰 이미지, 건너뛴 작은 이미지). 다룰 이미지는 쪽 면적 대비 보이는 면적이 min_share 이상인 것
    (왼쪽→오른쪽, 위→아래). 건너뛴 것은 쪽에 보이지만 그보다 작은 것.
    """
    area = page.rect.width * page.rect.height
    found, skipped = [], []
    for info in page.get_image_info(xrefs=True):
        full = fitz.Rect(info["bbox"])
        shown = full & page.rect
        if shown.is_empty or not full.width or not full.height or not area:
            continue
        if shown.width * shown.height / area < min_share:
            skipped.append(shown)
            continue
        square_inches = (full.width / 72) * (full.height / 72)
        dpi = (info["width"] * info["height"] / square_inches) ** 0.5
        tf = info.get("transform") or (1, 0, 0, 1, 0, 0)
        found.append(dict(xref=info.get("xref", 0), full=full, shown=shown,
                          native=[info["width"], info["height"]], dpi=dpi,
                          axis_aligned=abs(tf[1]) < 1e-6 and abs(tf[2]) < 1e-6))
    found.sort(key=lambda i: (round(i["shown"].x0), round(i["shown"].y0)))
    return found, skipped


def small_image_clusters(skipped, page_area, min_share, gap=2.0):
    """맞닿은(gap pt 이내) 작은 이미지 2개 이상이 이루는 영역 중 쪽 면적의 min_share 이상인 것.

    표 하나를 가로 띠 여러 장으로 쪼개 넣은 PDF는 이미지마다 작아 모두 건너뛰므로 조용히 0개가 된다.
    검출은 하지 않고 경고만 한다.
    """
    parent = list(range(len(skipped)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(skipped):
        for j in range(i + 1, len(skipped)):
            b = skipped[j]
            if a.x0 - gap <= b.x1 and b.x0 - gap <= a.x1 and a.y0 - gap <= b.y1 and b.y0 - gap <= a.y1:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(len(skipped)):
        groups.setdefault(find(i), []).append(skipped[i])
    out = []
    for rects in groups.values():
        if len(rects) < 2:
            continue
        box = rects[0]
        for r in rects[1:]:
            box = box | r
        share = box.width * box.height / page_area if page_area else 0
        if share >= min_share:
            out.append(dict(bbox_pt=[round(v, 2) for v in box], images=len(rects), page_share=round(share, 3)))
    return out


def render_image(page, fitz, im):
    """이미지를 원본 화소 격자에 맞춰 렌더(RGB). (PIL 이미지, 화소→쪽 좌표 함수, (가로 DPI, 세로 DPI)).

    이미지 bbox가 정수 화소 자리에 놓이게 가로·세로 배율을 따로 잡는다. 균일 배율로 렌더하면 bbox가
    화소 사이에 걸려 MuPDF가 반 화소 어긋나게 다시 보간하므로 조각이 원본보다 흐려진다(실측 선명도
    약 22% 저하). 회전·기울여 놓인 이미지만 균일 배율로 렌더한다.
    """
    full = im["full"]
    if im["axis_aligned"]:
        sx, sy = im["native"][0] / full.width, im["native"][1] / full.height
        mat = fitz.Matrix(sx, 0, 0, sy, -full.x0 * sx, -full.y0 * sy)
    else:
        sx = sy = im["dpi"] / 72
        mat = fitz.Matrix(sx, sy)
    pix = page.get_pixmap(matrix=mat, clip=im["shown"], alpha=False)
    if pix.n != 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    inv = ~mat
    ox, oy = pix.x, pix.y

    def to_pt(px, py):
        q = fitz.Point(ox + px, oy + py) * inv
        return round(q.x, 2), round(q.y, 2)

    return img, to_pt, (round(sx * 72, 1), round(sy * 72, 1))


def _overlap_ratio(a, b):
    """두 bbox(pt)의 겹친 넓이 / 작은 쪽 넓이."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / small if small > 0 else 0.0


def process_page(doc, fitz, n, opts, out):
    page = doc[n - 1]
    if page.rotation:
        page.remove_rotation()
    found, skipped = page_images(page, fitz, opts["min_share"])
    images, cands = [], []
    for idx, im in enumerate(found):
        img, to_pt, dpi_xy = render_image(page, fitz, im)
        images.append(dict(index=idx, xref=im["xref"], bbox_pt=[round(v, 2) for v in im["full"]],
                           native_px=im["native"], dpi=round(im["dpi"], 1), dpi_xy=list(dpi_xy),
                           rendered_px=[img.width, img.height]))
        area = im["shown"].width * im["shown"].height
        for g in detect_grids(img, dpi=im["dpi"]):
            x0, y0, x1, y1 = g["bbox_px"]
            bbox_pt = [*to_pt(x0, y0), *to_pt(x1, y1)]
            cands.append(dict(idx=idx, img=img, g=g, bbox_pt=bbox_pt, area=area, dpi=im["dpi"]))

    # 겹친 이미지: 위에 얹힌 표 이미지가 아래 큰 이미지의 렌더에도 찍혀 같은 표가 두 번 잡힌다.
    # 쪽 위 자리가 대부분(80%) 겹치면 더 작은 이미지(표 자체의 원본 화소)의 것만 남긴다.
    keep = []
    for c in sorted(cands, key=lambda c: c["area"]):
        if not any(k["idx"] != c["idx"] and _overlap_ratio(k["bbox_pt"], c["bbox_pt"]) >= 0.8 for k in keep):
            keep.append(c)
    dropped = len(cands) - len(keep)
    keep.sort(key=lambda c: cands.index(c))

    grids_out = []
    for c in keep:
        g = c["g"]
        gid = f"p{n:03d}.g{len(grids_out):02d}"
        header_rows = opts["header_rows_by_grid"].get(gid, opts["header_rows"])
        entry = dict(id=gid, image_index=c["idx"], bbox_px=g["bbox_px"],
                     bbox_pt=c["bbox_pt"], row_lines_px=g["row_lines_px"], col_lines_px=g["col_lines_px"],
                     rows=g["rows"], cols=g["cols"], dpi=round(c["dpi"], 1))
        entry.update(save_grid_crops(c["img"], g, gid, out, opts["max_width"], opts["band_rows"], header_rows))
        grids_out.append(entry)
    page_area = page.rect.width * page.rect.height
    return dict(page=n, images=images, grids=grids_out, duplicate_grids_dropped=dropped,
                skipped_small_images=len(skipped),
                small_image_clusters=small_image_clusters(skipped, page_area, opts["min_share"]),
                options=opts)


# ---------- 명령줄 ----------

class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse 기본(종료 코드 2) 대신 입력 오류 1
        self.print_usage(sys.stderr)
        print(f"입력 오류: {message}", file=sys.stderr)
        sys.exit(1)


def parse_header_rows(values):
    """--header-rows 값들 → (전체 적용 값 또는 None, {격자 id: 값}). 형식이 틀리면 ValueError.

    정수 하나는 모든 격자에, 'p025.g00=5'는 그 격자에만 적용한다. 격자 지정이 전체 값보다 앞선다.
    """
    overall, by_grid = None, {}
    for v in values or []:
        v = v.strip()
        m = re.fullmatch(r"(p\d{3}\.g\d{2})=(\d+)", v)
        if m:
            by_grid[m.group(1)] = int(m.group(2))
        elif re.fullmatch(r"\d+", v):
            if overall is not None:
                raise ValueError("--header-rows 정수(전체 적용)는 한 번만 줄 수 있다")
            overall = int(v)
        else:
            raise ValueError(f"--header-rows 값을 해석할 수 없다: {v!r} (예: 3 또는 p025.g00=5)")
    return overall, by_grid


def _args(argv):
    p = _Parser(description="PDF에 이미지로 박힌 표의 격자를 세고 판독용 확대 조각을 만든다(값은 읽지 않음).")
    p.add_argument("pdf", help="입력 PDF")
    p.add_argument("--out", required=True, help="조각과 manifest.json을 쓸 폴더. 같은 폴더에 다시 돌리면 "
                                               "처리한 쪽의 조각만 지우고 새로 만들며 매니페스트의 그 쪽만 바꾼다")
    p.add_argument("--pages", help="대상 쪽(1부터). 예: 4,25-27. 없으면 전체")
    p.add_argument("--max-width", type=int, default=2000, help="조각 최대 너비(px, 기본 2000)")
    p.add_argument("--band-rows", type=int, default=6, help="행 띠 하나가 덮는 행 간격 수(기본 6)")
    p.add_argument("--min-share", type=float, default=0.05, help="쪽 면적 대비 이미지 최소 비율(기본 0.05)")
    p.add_argument("--header-rows", action="append", metavar="N|pNNN.gXX=N",
                   help="머리글 행 간격 수를 직접 준다(자동 추정 대신). 정수는 모든 격자에, "
                        "p025.g00=5는 그 격자에만. 여러 번 줄 수 있다")
    a = p.parse_args(argv)
    if a.max_width < 1:
        p.error("--max-width는 1 이상이어야 한다")
    if a.band_rows < 1:
        p.error("--band-rows는 1 이상이어야 한다")
    if not 0 <= a.min_share <= 1:
        p.error("--min-share는 0~1 사이여야 한다")
    try:
        a.header_rows, a.header_rows_by_grid = parse_header_rows(a.header_rows)
    except ValueError as e:
        p.error(str(e))
    return a


CROP_NAME = re.compile(r"p\d{3}\.g\d{2}\.[^/\\]*\.png")


def _crops(out, page=None):
    """폴더의 조각 PNG(pNNN.gXX.*.png). page를 주면 그 쪽 것만."""
    pattern = "p*.png" if page is None else f"p{page:03d}.g*.png"
    return [f for f in out.glob(pattern) if CROP_NAME.fullmatch(f.name)]


def _load_previous(path, source_name):
    """(같은 문서로 만든 기존 매니페스트의 쪽 목록 {쪽: 항목}, 폴더의 옛 조각을 모두 버려야 하는가).

    매니페스트가 없거나 다른 문서의 것이거나 깨졌으면 폴더에 있는 조각을 믿을 수 없으므로 모두 버린다.
    """
    if not path.is_file():
        return {}, True
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(old, dict):
            raise ValueError("객체가 아니다")
    except (OSError, ValueError):
        print(f"경고: 기존 {path.name}을 읽지 못해 폴더의 옛 조각을 지우고 새로 쓴다.", file=sys.stderr)
        return {}, True
    if old.get("source") != source_name:
        print(f"경고: 기존 {path.name}은 다른 문서({old.get('source')})의 것이라 폴더의 옛 조각을 지우고 "
              "새로 쓴다.", file=sys.stderr)
        return {}, True
    return {p["page"]: p for p in old.get("pages", []) if isinstance(p, dict) and "page" in p}, False


def _summary(pages):
    grids = [g for p in pages for g in p["grids"]]
    return dict(pages=len(pages), images=sum(len(p["images"]) for p in pages), grids=len(grids),
                grids_per_page={str(p["page"]): len(p["grids"]) for p in pages},
                low_dpi_grids=sum(g["dpi"] < LOW_DPI for g in grids),
                skipped_small_images=sum(p.get("skipped_small_images", 0) for p in pages))


def _write_manifest(path, source_name, opts, by_page):
    pages = [by_page[k] for k in sorted(by_page)]
    data = dict(source=source_name, notice=NOTICE, values_certified=False, row_note=ROW_NOTE,
                coordinates="bbox_pt는 쪽 회전을 없앤 PDF 좌표(pt, 왼쪽 위 원점). *_px는 그 이미지를 원본 화소 "
                            "격자에 맞춰 렌더한 화소 좌표(rendered_px는 대개 native_px와 같다). 매니페스트의 "
                            "파일 경로는 이 폴더 기준 상대 경로. options는 마지막 실행의 것이고, 쪽마다 그 쪽을 "
                            "만든 실행의 options가 따로 있다.",
                options=opts, summary=_summary(pages), pages=pages)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def main(argv=None):
    started = time.monotonic()
    args = _args(argv)
    src = Path(args.pdf)
    if not src.is_file():
        print(f"입력 오류: 파일이 없다: {src}", file=sys.stderr)
        return 1
    out = Path(args.out)
    if out.exists() and not out.is_dir():
        print(f"입력 오류: --out이 폴더가 아니라 파일이다: {out}", file=sys.stderr)
        return 1
    fitz = _fitz()
    try:
        doc = fitz.open(src)
        if not doc.is_pdf:
            raise ValueError("PDF가 아니다")
    except Exception as e:
        print(f"입력 오류: PDF를 열 수 없다: {src} ({e})", file=sys.stderr)
        return 1
    if doc.needs_pass:
        print(f"입력 오류: 암호가 걸린 PDF다: {src}", file=sys.stderr)
        return 1
    try:
        pages = parse_pages(args.pages, doc.page_count) if args.pages else list(range(1, doc.page_count + 1))
    except ValueError as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return 1
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"입력 오류: 출력 폴더를 만들 수 없다: {out} ({e})", file=sys.stderr)
        return 1

    opts = dict(pages=args.pages and pages, max_width=args.max_width, band_rows=args.band_rows,
                min_share=args.min_share, header_rows=args.header_rows,
                header_rows_by_grid=args.header_rows_by_grid)
    manifest_path = out / "manifest.json"
    for gid in sorted(args.header_rows_by_grid):
        if int(gid[1:4]) not in pages:
            print(f"경고: --header-rows로 지정한 격자 {gid}는 이번에 처리하지 않는 쪽이라 적용하지 않는다.",
                  file=sys.stderr)
    by_page, stale = _load_previous(manifest_path, src.name)
    if stale:
        for old in _crops(out):
            old.unlink()
    try:
        for n in pages:
            # 다시 돌릴 때 띠 수가 줄어도 옛 조각이 남아 판독에 섞이지 않게, 이 쪽의 조각을 먼저 지운다
            by_page.pop(n, None)
            for old in _crops(out, n):
                old.unlink()
            try:
                r = process_page(doc, fitz, n, opts, out)
            except BaseException:
                # 도중에 멈춘 쪽의 조각은 매니페스트에 없으므로 남기지 않는다
                for part in _crops(out, n):
                    part.unlink(missing_ok=True)
                raise
            by_page[n] = r
            line = f"{n}쪽: 이미지 {len(r['images'])}개, 격자 {len(r['grids'])}개"
            if r["skipped_small_images"]:
                line += f", 작은 이미지 {r['skipped_small_images']}개 건너뜀"
            if r["duplicate_grids_dropped"]:
                line += f", 겹친 이미지의 중복 격자 {r['duplicate_grids_dropped']}개 뺌"
            print(line, flush=True)
            for c in r["small_image_clusters"]:
                print(f"  경고: {n}쪽에서 맞닿은 작은 이미지 {c['images']}개가 쪽의 {c['page_share']:.0%}를 차지한다. "
                      "표를 여러 조각 이미지로 쪼개 넣었을 수 있으니 쪽을 직접 확인한다(이 스크립트는 세지 않는다).",
                      flush=True)
    finally:
        # 도중에 멈춰도 처리한 쪽까지는 매니페스트와 폴더의 조각이 맞게 남긴다
        data = _write_manifest(manifest_path, src.name, opts, by_page)

    known = {g["id"] for n in pages for g in by_page[n]["grids"]}
    for gid in sorted(set(args.header_rows_by_grid) - known):
        if int(gid[1:4]) in pages:
            print(f"경고: --header-rows로 지정한 격자 {gid}가 없다.", file=sys.stderr)
    summary = data["summary"]
    print(f"합계: {summary['pages']}쪽, 이미지 {summary['images']}개, 격자 {summary['grids']}개"
          f" (유효 {LOW_DPI}DPI 미만 격자 {summary['low_dpi_grids']}개), {time.monotonic() - started:.1f}초")
    if not summary["grids"]:
        print("격자를 하나도 찾지 못했다. 표가 이미지가 아니거나 괘선이 없는 표일 수 있다.")
    print(f"매니페스트: {manifest_path}")
    print("다음 단계: 파서가 낸 표 개수와 쪽별로 견주어 빠진 표를 찾는다(도면이 격자로 잡혔는지 조각으로 확인).")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        # Windows 한국어 콘솔(cp949)에서 출력이 깨지거나 예외가 나지 않게 한다. 실행할 때만 바꾼다.
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
