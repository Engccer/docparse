"""image_tables.py: PDF에 이미지로 박힌 표의 격자를 세고 판독용 확대 조각을 만든다.

합성 PDF로 시험한다. Pillow로 격자 그림을 그리고 약 100DPI로 쪽에 넣는다(실제 카탈로그와 같은
저해상도). 스크립트 전체를 돌리는 시험은 PyMuPDF의 stdout 보관이 pytest 캡처와 엉키지 않게
별도 프로세스로 돌린다.
"""
import io
import json
import random
import subprocess
import sys

import pytest
from PIL import Image, ImageDraw

from _load import load

T = load("scripts/image_tables.py", "image_tables")

DPI = 100  # 합성 이미지가 쪽 위에 놓이는 유효 해상도


def draw_table(draw, x0, y0, row_heights, col_widths, *, width=1, text_pitch=None):
    """(x0, y0)에서 시작하는 괘선 표를 그린다. 행·열 경계선은 모두 끝에서 끝까지 긋는다.

    text_pitch를 주면 칸마다 그 간격으로 가짜 글자 줄(작은 검은 막대)을 채운다.
    """
    xs = [x0]
    for w in col_widths:
        xs.append(xs[-1] + w)
    ys = [y0]
    for h in row_heights:
        ys.append(ys[-1] + h)
    for y in ys:
        draw.line([(xs[0], y), (xs[-1], y)], fill=0, width=width)
    for x in xs:
        draw.line([(x, ys[0]), (x, ys[-1])], fill=0, width=width)
    if text_pitch:
        for top, bottom in zip(ys, ys[1:]):
            y = top + 5
            while y + 7 < bottom - 3:
                for left, right in zip(xs, xs[1:]):
                    draw.rectangle([left + 8, y, min(right - 8, left + 38), y + 6], fill=0)
                y += text_pitch
    return xs, ys


def image_pdf(path, images, *, pages=1, page_size=(612, 792)):
    """images: [(PIL.Image, (x_pt, y_pt))]를 각 쪽에 DPI 해상도로 넣은 PDF."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=page_size[0], height=page_size[1])
        for img, (x, y) in images:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            w = img.width * 72 / DPI
            h = img.height * 72 / DPI
            page.insert_image(pymupdf.Rect(x, y, x + w, y + h), stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return path


def run(source, out, *extra):
    return subprocess.run([sys.executable, T.__file__, str(source), "--out", str(out), *extra],
                          capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)


def manifest(out):
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def header_table_image():
    """머리글 2행(각 40px) + 본문 12행(각 20px) x 6열 표 하나."""
    img = Image.new("L", (640, 480), 255)
    draw_table(ImageDraw.Draw(img), 20, 60, [40, 40] + [20] * 12, [100] * 6)
    return img


# ---------- 순수 함수 ----------

def test_parse_pages_ranges_and_lists():
    assert T.parse_pages("4,25-27", 63) == [4, 25, 26, 27]
    assert T.parse_pages("3,1,3", 5) == [1, 3]
    for bad in ("0", "5-3", "a", "", "64", "1-64"):
        with pytest.raises(ValueError):
            T.parse_pages(bad, 63)


def test_detect_single_grid_rows_and_cols():
    grids = T.detect_grids(header_table_image(), dpi=DPI)
    assert len(grids) == 1
    g = grids[0]
    assert (g["rows"], g["cols"]) == (14, 6)
    assert len(g["row_lines_px"]) == 15 and len(g["col_lines_px"]) == 7
    x0, y0, x1, y1 = g["bbox_px"]
    assert abs(x0 - 20) <= 2 and abs(y0 - 60) <= 2 and abs(x1 - 620) <= 2 and abs(y1 - 380) <= 2


def test_detect_two_grids_in_one_image_top_to_bottom():
    img = Image.new("L", (640, 640), 255)
    d = ImageDraw.Draw(img)
    draw_table(d, 20, 20, [20] * 8, [120] * 5)
    draw_table(d, 20, 260, [24] * 10, [150] * 4)
    grids = T.detect_grids(img, dpi=DPI)
    assert [(g["rows"], g["cols"]) for g in grids] == [(8, 5), (10, 4)]
    assert grids[0]["bbox_px"][1] < grids[1]["bbox_px"][1]


def test_photo_like_image_has_no_grid():
    rnd = random.Random(7)
    img = Image.new("L", (640, 480), 200)
    d = ImageDraw.Draw(img)
    for _ in range(60):
        x, y = rnd.randrange(640), rnd.randrange(480)
        r = rnd.randrange(10, 80)
        d.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randrange(0, 256))
    for x in range(0, 640, 2):
        for y in range(0, 480, 3):
            if rnd.random() < 0.3:
                img.putpixel((x, y), rnd.randrange(0, 256))
    assert T.detect_grids(img, dpi=DPI) == []


def test_header_estimated_from_equal_spacing():
    # 머리글 2행(40px씩) + 본문 20px x 10행: 머리글이 본문 행의 정확히 2배여도 머리글로 본다
    assert T.estimate_header_rows([60, 100, 140] + list(range(160, 341, 20))) == 2
    # 괘선이 빠져 본문 간격이 2배·3배로 섞여도 정수배면 본문이다(마지막 덜 찬 묶음은 무시)
    assert T.estimate_header_rows([0, 15, 43, 58, 94, 166, 238, 274, 297]) == 3
    # 머리글 끝 행이 본문 행 높이와 같아도, 머리글 경계는 표 너비를 다 가로지르는 선으로 맞춘다
    assert T.estimate_header_rows([0, 25, 40] + list(range(60, 241, 20))) == 2
    assert T.estimate_header_rows([0, 25, 40] + list(range(60, 241, 20)), full_lines={0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}) == 3
    # 모든 행 간격이 같으면 머리글을 추정할 수 없다
    assert T.estimate_header_rows([0, 20, 40, 60, 80, 100]) is None


# ---------- 스크립트 전체 ----------

def test_single_grid_crops_and_manifest(tmp_path):
    src = image_pdf(tmp_path / "표.pdf", [(header_table_image(), (36, 72))])
    out = tmp_path / "out"
    r = run(src, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1쪽" in r.stdout and "격자 1개" in r.stdout
    assert "빠진 표" in r.stdout.strip().splitlines()[-1]

    m = manifest(out)
    assert m["source"] == "표.pdf"
    assert m["options"]["band_rows"] == 6 and m["options"]["max_width"] == 2000
    assert "보증하지 않는다" in m["notice"]
    page = m["pages"][0]
    assert page["page"] == 1
    im = page["images"][0]
    assert im["native_px"] == [640, 480]
    assert abs(im["dpi"] - DPI) < 1
    assert len(im["bbox_pt"]) == 4

    g = page["grids"][0]
    assert g["id"] == "p001.g00" and g["image_index"] == 0
    assert (g["rows"], g["cols"]) == (14, 6)
    # bbox_pt는 쪽 좌표: 이미지 원점(36, 72) + 픽셀 x 72/100
    assert abs(g["bbox_pt"][0] - (36 + 20 * 0.72)) < 2
    assert abs(g["bbox_pt"][1] - (72 + 60 * 0.72)) < 2
    assert g["overview"] == "p001.g00.overview.png"
    assert g["header"] == "p001.g00.header.png" and g["header_rows"] == 2
    assert g["band_mode"] == "rows"
    bands = g["bands"]
    assert [b["file"] for b in bands] == ["p001.g00.b00.png", "p001.g00.b01.png"]
    # 첫 띠는 머리글부터 본문 6행 + 아래 1행, 둘째 띠는 위로 1행 겹친다
    assert (bands[0]["row_from"], bands[0]["row_to"]) == (0, 8)
    assert (bands[1]["row_from"], bands[1]["row_to"]) == (7, 13)
    for rel in [g["overview"], g["header"]] + [b["file"] for b in bands]:
        assert (out / rel).is_file(), rel

    s = m["summary"]
    assert s["pages"] == 1 and s["images"] == 1 and s["grids"] == 1
    assert s["grids_per_page"] == {"1": 1}
    assert s["low_dpi_grids"] == 1

    # 둘째 띠에는 머리글 띠가 위에 붙어 있다
    with Image.open(out / bands[1]["file"]) as b1, Image.open(out / g["header"]) as hd:
        y0, y1 = bands[1]["bbox_px"][1], bands[1]["bbox_px"][3]
        assert b1.height >= hd.height + round((y1 - y0) * g["scale"]) - 2
        # 머리글과 띠 사이 빨간 구분 막대
        assert b1.getpixel((b1.width // 2, hd.height + 2))[:3] == (220, 0, 0)
        assert b1.width == hd.width
    assert g["header_source"] == "estimated" and bands[1]["header_attached"] and not bands[0]["header_attached"]


def test_crop_width_respects_max_width_and_scale_cap(tmp_path):
    src = image_pdf(tmp_path / "w.pdf", [(header_table_image(), (36, 72))])
    out = tmp_path / "o1"
    assert run(src, out, "--max-width", "1000").returncode == 0
    g = manifest(out)["pages"][0]["grids"][0]
    assert 1 < g["scale"] <= 1000 / 600
    for rel in [g["overview"], g["header"]] + [b["file"] for b in g["bands"]]:
        with Image.open(out / rel) as im:
            assert im.width <= 1000, (rel, im.width)

    out2 = tmp_path / "o2"
    assert run(src, out2, "--max-width", "9000").returncode == 0
    assert manifest(out2)["pages"][0]["grids"][0]["scale"] == 4


def test_uniform_rows_have_no_header_unless_given(tmp_path):
    img = Image.new("L", (640, 480), 255)
    draw_table(ImageDraw.Draw(img), 20, 20, [24] * 16, [100] * 6)
    src = image_pdf(tmp_path / "u.pdf", [(img, (36, 72))])
    out = tmp_path / "o"
    assert run(src, out).returncode == 0
    g = manifest(out)["pages"][0]["grids"][0]
    assert g["header"] is None and g["header_rows"] is None
    assert not list(out.glob("*.header.png"))
    assert g["bands"][0]["row_from"] == 0

    out2 = tmp_path / "o2"
    assert run(src, out2, "--header-rows", "1").returncode == 0
    g2 = manifest(out2)["pages"][0]["grids"][0]
    assert g2["header"] == "p001.g00.header.png" and g2["header_rows"] == 1
    assert g2["header_source"] == "given"


def test_sparse_row_lines_fall_back_to_fixed_bands(tmp_path):
    """행 경계선이 글자 3줄마다 하나뿐이면 선 간격 띠가 너무 커서 일정 높이 띠로 자른다."""
    img = Image.new("L", (640, 700), 255)
    draw_table(ImageDraw.Draw(img), 20, 20, [48] * 13, [100] * 6, text_pitch=16)
    src = image_pdf(tmp_path / "s.pdf", [(img, (36, 36))])
    out = tmp_path / "o"
    assert run(src, out).returncode == 0
    g = manifest(out)["pages"][0]["grids"][0]
    assert g["band_mode"] == "fixed"
    assert len(g["bands"]) >= 5
    assert all(b["row_from"] is None for b in g["bands"])
    # 띠끼리 겹친다
    for a, b in zip(g["bands"], g["bands"][1:]):
        assert b["bbox_px"][1] < a["bbox_px"][3]


def test_no_grid_is_still_success(tmp_path):
    rnd = random.Random(3)
    img = Image.new("L", (640, 480), 230)
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x, y, r = rnd.randrange(640), rnd.randrange(480), rnd.randrange(10, 60)
        d.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randrange(0, 256))
    src = image_pdf(tmp_path / "p.pdf", [(img, (36, 72))])
    out = tmp_path / "o"
    r = run(src, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "격자를 하나도 찾지 못했다" in r.stdout
    assert manifest(out)["summary"]["grids"] == 0


def test_pages_option_limits_pages(tmp_path):
    src = image_pdf(tmp_path / "m.pdf", [(header_table_image(), (36, 72))], pages=3)
    out = tmp_path / "o"
    r = run(src, out, "--pages", "2-3")
    assert r.returncode == 0, r.stdout + r.stderr
    m = manifest(out)
    assert [p["page"] for p in m["pages"]] == [2, 3]
    assert m["options"]["pages"] == [2, 3]
    assert m["pages"][0]["grids"][0]["id"] == "p002.g00"
    assert (out / "p003.g00.overview.png").is_file()
    assert not (out / "p001.g00.overview.png").exists()


def test_small_images_below_min_share_are_ignored(tmp_path):
    small = header_table_image().resize((160, 120))
    src = image_pdf(tmp_path / "small.pdf", [(small, (36, 72))])
    out = tmp_path / "o"
    assert run(src, out).returncode == 0
    assert manifest(out)["summary"]["images"] == 0


@pytest.mark.parametrize("extra", [["--pages", "9"], ["--pages", "x"], ["--max-width", "0"],
                                   ["--band-rows", "0"], ["--min-share", "2"]])
def test_input_errors_exit_1(tmp_path, extra):
    src = image_pdf(tmp_path / "e.pdf", [(header_table_image(), (36, 72))])
    r = run(src, tmp_path / "o", *extra)
    assert r.returncode == 1, r.stdout + r.stderr


def test_missing_or_invalid_file_exit_1(tmp_path):
    assert run(tmp_path / "없음.pdf", tmp_path / "o").returncode == 1
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert run(bad, tmp_path / "o").returncode == 1


def test_dark_bar_row_does_not_split_table():
    """짙게 채운 구분 행(예: CLASS 900) 위아래로 세로선이 끊겨도 표 하나로 묶고 띠 가장자리를 경계선으로 친다."""
    img = Image.new("L", (640, 520), 255)
    d = ImageDraw.Draw(img)
    xs = [20 + 100 * i for i in range(7)]
    draw_table(d, 20, 20, [40] + [20] * 4, [100] * 6)       # 머리글 + 위 본문, 아래 끝 y=140
    d.rectangle([20, 140, 620, 157], fill=40)                 # 18px 짙은 띠
    d.text((280, 143), "CLASS 900", fill=255)
    draw_table(d, 20, 158, [20] * 8, [100] * 6)               # 띠 아래 본문
    grids = T.detect_grids(img, dpi=DPI)
    assert len(grids) == 1, [g["bbox_px"] for g in grids]
    g = grids[0]
    assert g["cols"] == 6 and len(xs) == 7
    assert any(abs(y - 140) <= 2 for y in g["row_lines_px"])
    assert any(abs(y - 158) <= 2 for y in g["row_lines_px"])


def test_small_irregular_group_is_not_a_table_but_small_regular_table_is():
    img = Image.new("L", (900, 500), 255)
    d = ImageDraw.Draw(img)
    # 도면 흉내: 폭이 이미지의 1/4쯤이고 행 간격이 제각각
    draw_table(d, 20, 20, [15, 50, 9, 33], [40, 70, 50, 60])
    assert T.detect_grids(img, dpi=DPI) == []
    # 같은 폭이라도 같은 간격 행이 이어지면 작은 표로 본다
    draw_table(d, 400, 200, [30] + [18] * 6, [60] * 4)
    grids = T.detect_grids(img, dpi=DPI)
    assert [(g["rows"], g["cols"]) for g in grids] == [(7, 4)]


def test_open_sided_half_width_table_with_uneven_rows():
    """양옆 테두리가 없고 행 높이가 제각각인 반쪽 폭 표(공차표 꼴)도 표로 본다. 긴 가로선 양 끝이 좌우 경계다."""
    img = Image.new("L", (900, 700), 255)
    d = ImageDraw.Draw(img)
    ys = [40, 70, 130, 160, 240, 270, 330, 420, 460, 560, 600]
    for y in ys:
        d.line([(20, y), (420, y)], fill=0)
    for x in (140, 290):
        d.line([(x, ys[0]), (x, ys[-1])], fill=0)
    grids = T.detect_grids(img, dpi=DPI)
    assert [(g["rows"], g["cols"]) for g in grids] == [(10, 3)]
    cols = grids[0]["col_lines_px"]
    assert abs(cols[0] - 20) <= 2 and abs(cols[-1] - 420) <= 2


# ---------- 리뷰 반영(2026-11-16) ----------

def _pdf_items(path, items, page_size=(612, 792), pages=1, encrypt=False):
    """items: [(PIL 이미지, Rect 4-튜플(pt))]. 화소 격자에 안 맞는 자리·가로세로 다른 DPI를 그대로 넣는다."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=page_size[0], height=page_size[1])
        for img, rect in items:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            page.insert_image(pymupdf.Rect(*rect), stream=buf.getvalue(), keep_proportion=False)
    if encrypt:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    else:
        doc.save(path)
    doc.close()
    return path


def _png_names(out):
    return {p.name for p in out.glob("*.png")}


def _referenced(m):
    names = set()
    for pg in m["pages"]:
        for g in pg["grids"]:
            names.add(g["overview"])
            if g["header"]:
                names.add(g["header"])
            names.update(b["file"] for b in g["bands"])
    return names


def test_render_is_aligned_to_native_pixels(tmp_path):
    """정수 화소에 놓이지 않은 이미지도 원본 화소 그대로 렌더한다(배율 1 조각 = 원본 화소)."""
    src_img = header_table_image()
    x, y = 36.3, 72.7
    src = _pdf_items(tmp_path / "frac.pdf", [(src_img, (x, y, x + 460.8, y + 345.6))])
    out = tmp_path / "o"
    r = run(src, out, "--max-width", "10")
    assert r.returncode == 0, r.stdout + r.stderr
    m = manifest(out)
    im = m["pages"][0]["images"][0]
    assert im["rendered_px"] == im["native_px"] == [640, 480]
    g = m["pages"][0]["grids"][0]
    assert g["scale"] == 1
    x0, y0, x1, y1 = g["bbox_px"]
    ref = src_img.convert("RGB").crop((max(0, x0 - 3), max(0, y0 - 3), min(640, x1 + 3), min(480, y1 + 3)))
    from PIL import ImageChops, ImageStat
    with Image.open(out / g["overview"]) as ov:
        assert ov.size == ref.size
        diff = ImageStat.Stat(ImageChops.difference(ov.convert("L"), ref.convert("L"))).mean[0]
    assert diff < 1.0, diff
    # 쪽 좌표 환산도 실제 놓인 자리 기준
    assert abs(g["bbox_pt"][0] - (x + x0 * 0.72)) < 0.5 and abs(g["bbox_pt"][1] - (y + y0 * 0.72)) < 0.5


def test_render_handles_different_horizontal_and_vertical_dpi(tmp_path):
    src = _pdf_items(tmp_path / "aniso.pdf", [(header_table_image(), (40, 50, 40 + 460.8, 50 + 230.4))])
    out = tmp_path / "o"
    assert run(src, out).returncode == 0
    m = manifest(out)
    im = m["pages"][0]["images"][0]
    assert im["rendered_px"] == im["native_px"] == [640, 480]
    assert im["dpi_xy"] == [100.0, 150.0]
    g = m["pages"][0]["grids"][0]
    assert (g["rows"], g["cols"]) == (14, 6)
    assert abs(g["bbox_pt"][3] - (50 + 380 * 0.48)) < 1


def _open_top_table():
    """위 테두리가 없고(세로선은 첫 행 위까지 올라감) 14px 행 60개인 표."""
    img = Image.new("L", (660, 900), 255)
    d = ImageDraw.Draw(img)
    xs = [20 + 100 * i for i in range(7)]
    ys = [20 + 14 * i for i in range(61)]
    for yy in ys[1:]:
        d.line([(xs[0], yy), (xs[-1], yy)], fill=0)
    for xx in xs:
        d.line([(xx, ys[0]), (xx, ys[-1])], fill=0)
    return img


def test_bands_cover_whole_grid_height(tmp_path):
    src = image_pdf(tmp_path / "c.pdf", [(_open_top_table(), (36, 36))])
    out = tmp_path / "o"
    assert run(src, out).returncode == 0
    m = manifest(out)
    grids = m["pages"][0]["grids"]
    assert grids
    for g in grids:
        tops = [b["bbox_px"][1] for b in g["bands"]]
        bottoms = [b["bbox_px"][3] for b in g["bands"]]
        assert min(tops) <= g["bbox_px"][1], (g["id"], tops[:1], g["bbox_px"])
        assert max(bottoms) >= g["bbox_px"][3], (g["id"], bottoms[-1:], g["bbox_px"])


def test_rerun_same_folder_replaces_only_processed_pages(tmp_path):
    src = image_pdf(tmp_path / "two.pdf", [(header_table_image(), (36, 72))], pages=2)
    out = tmp_path / "o"
    assert run(src, out).returncode == 0
    first = manifest(out)
    p1_before = first["pages"][0]
    r = run(src, out, "--pages", "2", "--header-rows", "p002.g00=1", "--band-rows", "20")
    assert r.returncode == 0, r.stdout + r.stderr
    m = manifest(out)
    assert [p["page"] for p in m["pages"]] == [1, 2]
    assert m["pages"][0] == p1_before
    g2 = m["pages"][1]["grids"][0]
    assert g2["header_rows"] == 1 and g2["header_source"] == "given"
    assert len(g2["bands"]) == 1
    assert m["summary"]["pages"] == 2 and m["summary"]["grids"] == 2
    assert m["summary"]["grids_per_page"] == {"1": 1, "2": 1}
    # 폴더의 조각은 모두 매니페스트에 있다(옛 띠가 남지 않는다)
    assert _png_names(out) == _referenced(m)


def test_header_rows_option_forms(tmp_path):
    src = image_pdf(tmp_path / "h.pdf", [(header_table_image(), (36, 72))], pages=2)
    out = tmp_path / "o"
    r = run(src, out, "--header-rows", "3", "--header-rows", "p002.g00=1")
    assert r.returncode == 0, r.stdout + r.stderr
    m = manifest(out)
    assert [p["grids"][0]["header_rows"] for p in m["pages"]] == [3, 1]
    assert m["options"]["header_rows"] == 3
    assert m["options"]["header_rows_by_grid"] == {"p002.g00": 1}
    for bad in (["--header-rows", "p2.g0=1"], ["--header-rows", "p002.g00=x"], ["--header-rows", "1", "--header-rows", "2"]):
        assert run(src, tmp_path / "bad", *bad).returncode == 1, bad


@pytest.mark.parametrize("bar", [30, 45, 60])
def test_thick_dark_header_bar_table_is_detected(bar):
    img = Image.new("L", (640, 560), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 620, 20 + bar], fill=30)
    for i in range(6):
        d.text((40 + 100 * i, 20 + bar // 2 - 5), f"COL{i}", fill=255)
    draw_table(d, 20, 21 + bar, [20] * 14, [100] * 6)
    grids = T.detect_grids(img, dpi=DPI)
    assert len(grids) == 1, [g["bbox_px"] for g in grids]
    g = grids[0]
    assert g["cols"] == 6
    assert any(abs(y - 20) <= 2 for y in g["row_lines_px"])
    assert any(abs(y - (20 + bar)) <= 3 for y in g["row_lines_px"])


def test_thick_dark_separator_bar_in_middle():
    img = Image.new("L", (640, 560), 255)
    d = ImageDraw.Draw(img)
    draw_table(d, 20, 20, [20] * 6, [100] * 6)
    d.rectangle([20, 140, 620, 176], fill=40)
    d.text((280, 152), "CLASS 1500", fill=255)
    draw_table(d, 20, 177, [20] * 8, [100] * 6)
    grids = T.detect_grids(img, dpi=DPI)
    assert len(grids) == 1 and grids[0]["cols"] == 6, [(g["bbox_px"], g["cols"]) for g in grids]


def test_overlapping_images_do_not_double_count(tmp_path):
    bg = Image.new("L", (850, 1100), 245)
    src = _pdf_items(tmp_path / "bg.pdf", [(bg, (0, 0, 612, 792)),
                                           (header_table_image(), (36, 72, 36 + 460.8, 72 + 345.6))])
    out = tmp_path / "o"
    r = run(src, out)
    assert r.returncode == 0, r.stdout + r.stderr
    page = manifest(out)["pages"][0]
    assert len(page["images"]) == 2
    assert len(page["grids"]) == 1
    tbl = [i["index"] for i in page["images"] if i["native_px"] == [640, 480]][0]
    assert page["grids"][0]["image_index"] == tbl
    assert page["duplicate_grids_dropped"] == 1
    assert _png_names(out) == _referenced(manifest(out))


def test_skipped_small_images_are_reported(tmp_path):
    big = Image.new("L", (700, 900), 255)
    draw_table(ImageDraw.Draw(big), 20, 20, [20] * 42, [110] * 6)
    items = [(big.crop((0, yy, 700, yy + 50)), (36, 36 + yy * 0.72, 36 + 504, 36 + (yy + 50) * 0.72))
             for yy in range(0, 900, 50)]
    src = _pdf_items(tmp_path / "strips.pdf", items)
    out = tmp_path / "o"
    r = run(src, out)
    assert r.returncode == 0, r.stdout + r.stderr
    page = manifest(out)["pages"][0]
    assert page["skipped_small_images"] == 18
    assert len(page["small_image_clusters"]) == 1
    assert page["small_image_clusters"][0]["images"] == 18
    assert "작은 이미지 18개" in r.stdout and "경고" in r.stdout


def test_out_is_file_or_encrypted_pdf_is_input_error(tmp_path):
    src = image_pdf(tmp_path / "a.pdf", [(header_table_image(), (36, 72))])
    afile = tmp_path / "afile"
    afile.write_text("x")
    r = run(src, afile)
    assert r.returncode == 1 and "입력 오류" in r.stderr and "Traceback" not in r.stderr, r.stderr
    enc = _pdf_items(tmp_path / "enc.pdf", [(header_table_image(), (36, 72, 496.8, 417.6))], encrypt=True)
    r = run(enc, tmp_path / "o")
    assert r.returncode == 1 and "입력 오류" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_fixed_band_edges_do_not_cut_text_rows(tmp_path):
    """fixed 모드 띠의 안쪽 가장자리는 글자 줄을 지나가지 않는다."""
    img = Image.new("L", (640, 700), 255)
    _, ys = draw_table(ImageDraw.Draw(img), 20, 20, [48] * 13, [100] * 6, text_pitch=16)
    text_rows = []
    for top, bottom in zip(ys, ys[1:]):
        yy = top + 5
        while yy + 7 < bottom - 3:
            text_rows.append((yy, yy + 6))
            yy += 16
    src = image_pdf(tmp_path / "s.pdf", [(img, (36, 36))])
    out = tmp_path / "o"
    assert run(src, out).returncode == 0
    g = manifest(out)["pages"][0]["grids"][0]
    assert g["band_mode"] == "fixed"
    gy0, gy1 = g["bbox_px"][1], g["bbox_px"][3]
    for b in g["bands"]:
        for e in (b["bbox_px"][1], b["bbox_px"][3]):
            if gy0 + 1 < e < gy1 - 1:
                assert not any(t0 - 0.5 <= e <= t1 + 1.5 for t0, t1 in text_rows), (b["file"], e)


def test_dash_inside_cell_is_not_a_row_line():
    """칸 안의 '-' 표시(짧은 가로 획)는 행 경계선이 아니다. 두 세로선 사이를 잇는 짧은 선은 경계선이다."""
    img = Image.new("L", (640, 480), 255)
    d = ImageDraw.Draw(img)
    xs, ys = draw_table(d, 20, 20, [40] * 10, [100] * 6)
    d.line([(xs[2] + 7, ys[3] + 20), (xs[2] + 90, ys[3] + 20)], fill=0, width=2)  # 칸 안 긴 대시(세로선에 가까움)
    d.line([(xs[1], ys[0] + 20), (xs[3], ys[0] + 20)], fill=0)  # 병합 머리글 아래 짧은 선(두 칸)
    g = T.detect_grids(img, dpi=DPI)[0]
    assert not any(abs(y - (ys[3] + 20.5)) <= 3 for y in g["row_lines_px"]), g["row_lines_px"]
    assert any(abs(y - (ys[0] + 20)) <= 2 for y in g["row_lines_px"]), g["row_lines_px"]


def test_dash_row_filling_narrow_cells_is_not_a_row_line():
    """좁은 열을 거의 채운 대시가 한 행에 줄줄이 있어도(길이 합이 크더라도) 세로선에 닿지 않으면 경계선이 아니다."""
    img = Image.new("L", (640, 480), 255)
    d = ImageDraw.Draw(img)
    xs, ys = draw_table(d, 20, 60, [24] * 14, [40] * 15)
    for c in range(15):
        for r in range(14):
            if r == 6:
                d.line([(xs[c] + 3, ys[r] + 12), (xs[c + 1] - 3, ys[r] + 12)], fill=0, width=2)
            else:
                d.text((xs[c] + 6, ys[r] + 6), "12.5", fill=0)
    g = T.detect_grids(img, dpi=DPI)[0]
    assert g["rows"] == 14, g["row_lines_px"]


def test_digit_baseline_filling_narrow_column_is_not_a_row_line():
    """좁은 열을 꽉 채운 숫자의 밑변·윗변은 양 끝이 세로선에 닿아도 바로 위아래에 글자 잉크가 있어 경계선이 아니다."""
    img = Image.new("L", (640, 480), 255)
    d = ImageDraw.Draw(img)
    xs, ys = draw_table(d, 20, 60, [24] * 14, [30] * 20)
    for c in (3, 9, 15):
        gx0, gx1, gy = xs[c] + 1, xs[c + 1] - 1, ys[5] + 8
        d.rectangle([gx0, gy, gx1, gy + 8], outline=0)
        for x in range(gx0 + 4, gx1 - 1, 4):  # 숫자 획
            d.line([(x, gy), (x, gy + 8)], fill=0, width=2)
    g = T.detect_grids(img, dpi=DPI)[0]
    assert g["rows"] == 14, g["row_lines_px"]


def test_other_document_or_broken_manifest_clears_old_crops(tmp_path):
    out = tmp_path / "o"
    two = image_pdf(tmp_path / "two.pdf", [(header_table_image(), (36, 72))], pages=2)
    assert run(two, out).returncode == 0
    keep = out / "memo.png"  # 조각 이름 규칙이 아닌 파일은 건드리지 않는다
    Image.new("L", (4, 4), 255).save(keep)
    one = image_pdf(tmp_path / "one.pdf", [(header_table_image(), (36, 72))], pages=1)
    r = run(one, out)
    assert r.returncode == 0 and "다른 문서" in r.stderr, r.stderr
    m = manifest(out)
    assert [p["page"] for p in m["pages"]] == [1]
    assert _png_names(out) - {"memo.png"} == _referenced(m) and keep.exists()
    # 깨진 매니페스트: 옛 조각을 모두 버리고 새로 쓴다
    (out / "p009.g00.b00.png").write_bytes(b"x")
    (out / "manifest.json").write_text("{", encoding="utf-8")
    r = run(one, out, "--pages", "1")
    assert r.returncode == 0 and "읽지 못해" in r.stderr, r.stderr
    assert _png_names(out) - {"memo.png"} == _referenced(manifest(out))


def test_crash_mid_page_leaves_no_unlisted_crops(tmp_path, monkeypatch):
    src = image_pdf(tmp_path / "two.pdf", [(header_table_image(), (36, 72))], pages=2)
    out = tmp_path / "o"
    real = T.save_grid_crops

    def boom(img, grid, gid, *a, **k):
        res = real(img, grid, gid, *a, **k)
        if gid.startswith("p002"):
            raise RuntimeError("중단 흉내")
        return res

    monkeypatch.setattr(T, "save_grid_crops", boom)
    with pytest.raises(RuntimeError):
        T.main([str(src), "--out", str(out)])
    m = manifest(out)
    assert [p["page"] for p in m["pages"]] == [1]
    assert _png_names(out) == _referenced(m)


def test_header_rows_for_unprocessed_page_warns(tmp_path):
    src = image_pdf(tmp_path / "two.pdf", [(header_table_image(), (36, 72))], pages=2)
    r = run(src, tmp_path / "o", "--pages", "1", "--header-rows", "p002.g00=1")
    assert r.returncode == 0
    assert "p002.g00" in r.stderr and "처리하지 않는 쪽" in r.stderr, r.stderr


@pytest.mark.parametrize("gap", [0, 3])
def test_dark_rows_with_faint_columns_keep_grid(gap):
    """진한 가로선 + 옅은 세로선 표: 세로선이 가로선 근처에서 이진화가 끊겨도(또는 실제로 3px 떨어져도) 격자가 남는다."""
    img = Image.new("L", (700, 560), 255)
    d = ImageDraw.Draw(img)
    xs = [20 + 110 * i for i in range(7)]
    ys = [30 + 40 * i for i in range(13)]
    for x in xs:
        for t, b in zip(ys, ys[1:]):
            d.line([(x, t + gap), (x, b - gap)], fill=220 if gap == 0 else 0)
    for y in ys:
        d.line([(xs[0], y), (xs[-1], y)], fill=0, width=2)
    for r, (t, b) in enumerate(zip(ys, ys[1:])):
        for c, (l, rr) in enumerate(zip(xs, xs[1:])):
            d.text((l + 40, t + 15), f"{r * 3 + c}.{c}", fill=0)
    grids = T.detect_grids(img, dpi=DPI)
    assert [(g["rows"], g["cols"]) for g in grids] == [(12, 6)]


# ---------- 머리글 추정 보강(2026-11-23) ----------

def test_header_from_short_header_lines_when_spacing_cannot_tell():
    """간격으로 못 정해도, 격자 너비를 다 가로지르지 않는 선(병합 머리글 아래 짧은 선)만 이어지다 처음 나온
    전폭선을 머리글 끝으로 본다. 본문이 묶음 2개뿐인 짧은 표(실측)."""
    rl = [0, 19, 38, 57, 80, 158, 236]
    assert T.estimate_header_rows(rl) is None  # 간격만으로는 본문 간격이 3개 미만이라 못 정한다
    assert T.estimate_header_rows(rl, full_lines={0, 4, 5, 6}) == 4
    # 첫 선부터 전폭선이면 머리글 안의 짧은 선이라는 근거가 없으므로 정하지 않는다
    assert T.estimate_header_rows([0, 44, 93, 142, 190, 239, 288, 337, 370], full_lines=set(range(9))) is None
    # 전폭선 아래 본문 간격이 2개 미만이거나 머리글이 격자 높이의 절반을 넘으면 정하지 않는다
    assert T.estimate_header_rows([0, 19, 38, 57, 80, 158], full_lines={0, 4, 5}) is None
    assert T.estimate_header_rows([0, 40, 80, 120, 160, 190, 220], full_lines={0, 4, 5, 6}) is None
    # 간격으로 정해지는 표는 전과 같다
    assert T.estimate_header_rows([0, 25, 40] + list(range(60, 241, 20)), full_lines={0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}) == 3


def test_short_table_with_merged_header_gets_header_band():
    """머리글 3단(병합 칸 아래 짧은 선 2개) + 본문 묶음 2개(글자 3줄마다 괘선)인 표의 머리글을 추정한다."""
    img = Image.new("L", (760, 340), 255)
    d = ImageDraw.Draw(img)
    xs = [20 + 120 * i for i in range(7)]
    ys = [20, 45, 70, 95, 175, 255]
    for y in (ys[0], ys[3], ys[4], ys[5]):
        d.line([(xs[0], y), (xs[-1], y)], fill=0)
    d.line([(xs[2], ys[1]), (xs[5], ys[1])], fill=0)  # 병합 머리글 아래(3칸)
    d.line([(xs[3], ys[2]), (xs[5], ys[2])], fill=0)  # 그 아래 병합(2칸)
    for x in (xs[0], xs[1], xs[2], xs[5], xs[6]):
        d.line([(x, ys[0]), (x, ys[-1])], fill=0)
    d.line([(xs[3], ys[1]), (xs[3], ys[-1])], fill=0)
    d.line([(xs[4], ys[2]), (xs[4], ys[-1])], fill=0)
    for top in (ys[3], ys[4]):
        for i in range(3):
            for l, r in zip(xs, xs[1:]):
                d.rectangle([l + 30, top + 10 + 24 * i, l + 80, top + 18 + 24 * i], fill=0)
    g = T.detect_grids(img, dpi=DPI)[0]
    assert g["rows"] == 5 and g["cols"] == 6, (g["row_lines_px"], g["col_lines_px"])
    hr, _, _ = T.plan_bands(g, 6, None)
    assert hr == 3


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_page_is_rendered_on_native_pixels(tmp_path, rotation):
    """/Rotate 90·270 쪽: 회전을 없애면 이미지가 90도 돌아 놓이는데, 그래도 원본 화소와 1:1로 렌더한다
    (가로·세로 화소 수가 바뀐 채 맞는다). 표는 쪽을 보이는 방향으로 센다."""
    pymupdf = pytest.importorskip("pymupdf")
    src_img = header_table_image()
    buf = io.BytesIO()
    src_img.convert("RGB").save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(pymupdf.Rect(36.3, 72.7, 36.3 + 460.8, 72.7 + 345.6), stream=buf.getvalue())
    page.set_rotation(rotation)
    path = tmp_path / f"rot{rotation}.pdf"
    doc.save(path)
    doc.close()
    out = tmp_path / "o"
    r = run(path, out, "--max-width", "10")
    assert r.returncode == 0, r.stdout + r.stderr
    m = manifest(out)
    im = m["pages"][0]["images"][0]
    assert im["native_px"] == [640, 480] and im["rendered_px"] == [480, 640]
    g = m["pages"][0]["grids"][0]
    assert (g["rows"], g["cols"]) == (6, 14) and g["scale"] == 1
    turned = src_img.convert("RGB").transpose(Image.Transpose.ROTATE_270 if rotation == 90 else Image.Transpose.ROTATE_90)
    x0, y0, x1, y1 = g["bbox_px"]
    ref = turned.crop((max(0, x0 - 3), max(0, y0 - 3), min(480, x1 + 3), min(640, y1 + 3)))
    from PIL import ImageChops, ImageStat
    with Image.open(out / g["overview"]) as ov:
        assert ov.size == ref.size
        diff = ImageStat.Stat(ImageChops.difference(ov.convert("L"), ref.convert("L"))).mean[0]
    assert diff < 1.0, diff
