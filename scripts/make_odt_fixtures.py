"""공개 가능한 합성 ODT 회귀 자료 생성기(표준 라이브러리만, 결정론적).

실명·실제 기관 없이 직접 만든 ODT를 만든다. 같은 명세에서 "이상적인 파싱 결과" 마크다운
(<이름>.reference.md)도 함께 써서, 파서 출력·검증기(odt_verify.py) 시험의 기준으로 쓴다.
zip 항목 시각을 고정하므로 다시 실행해도 바이트 단위로 같은 파일이 나온다.

Usage:
    python make_odt_fixtures.py <출력_폴더> [이름 ...]
    python make_odt_fixtures.py --list

종료 코드: 성공 0, 인자 오류 2.
"""

import struct
import sys
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ZIP_TIME = (2026, 1, 1, 0, 0, 0)
PLACEHOLDER = "본문을 입력하십시오"

NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'office:version="1.3"'
)

# 블록 명세: ("h", 수준, 글) / ("p", 글) / ("table", {"header": [...], "rows": [[...]]})
# / ("image", 파일이름, 대체텍스트) / ("textbox", [글, ...])
# 표 셀은 글(str), 여러 문단(list), 또는 {"text": str|list, "colspan": n, "rowspan": n}.
FIXTURES = {
    "table_header_merge": {
        "title": "학급별 독서 현황(합성)",
        "blocks": [
            ("h", 1, "학급별 독서 현황(합성 자료)"),
            ("p", "아래 표는 회귀 시험을 위해 만든 가상의 수치이다."),
            ("table", {
                "header": ["학년", "학급", "1학기", "2학기"],
                "rows": [
                    [{"text": "1학년", "rowspan": 2}, "1반", "112권", "130권"],
                    ["2반", "98권", ["104권", "(추정)"]],
                    ["2학년", "1반", {"text": "자료 없음", "colspan": 2}],
                    [{"text": "합계", "colspan": 2}, "210권", "234권"],
                ],
            }),
            ("p", "수치는 모두 합성값이며 실제 학교와 관계없다."),
        ],
    },
    "gongmun": {
        "title": "합성 공문",
        "header": "가상시 교육지원청 내부 문서",
        "footer": "가상시 교육지원청",
        "blocks": [
            ("p", "가상시 교육지원청"),
            ("p", "수신  수신자 참조"),
            ("p", "(경유)"),
            ("p", "제목  합성 회귀 자료 점검 협조 요청"),
            ("p", "1. 관련: 가상시 교육지원청 정보화팀-0000(2026. 1. 2.)"),
            ("p", "2. 아래와 같이 점검 회의를 열고자 하니 협조하여 주시기 바랍니다."),
            ("table", {
                "header": ["구분", "일시", "장소"],
                "rows": [
                    ["1차 회의", "2026. 1. 5. 15;00", "가상중학교 회의실"],
                    ["2차 회의", "2026. 1. 12. 14:00", "온라인"],
                ],
            }),
            ("textbox", ["※ 회의 자료는 사전에 배포합니다."]),
            ("p", "<붙임> 합성 자료 목록 1부.  끝."),
            ("p", "가상시 교육지원청 교육장"),
            ("table", {
                "header": ["기안자", "검토자", "결재권자"],
                "rows": [["주무관 홍길순", "", "과장 김예시"]],
            }),
            ("p", "시행 정보화팀-1234 (2026. 1. 3.)  접수 가상중학교-0001 (2026. 1. 4.)"),
            ("p", "우 00000 가상시 예시로 1 / 전화 000-0000-0000 / 전자우편 office@example.com / 공개"),
        ],
    },
    "image_caption": {
        "title": "이미지 포함 안내문(합성)",
        "blocks": [
            ("p", "다음 그림은 합성 배치도이다."),
            ("image", "layout.png", "합성 배치도: 교실 네 칸"),
            ("p", "그림 1. 학교 배치도(합성)"),
            ("p", "그림 속 글자는 파서가 텍스트로 추출하지 않는다."),
        ],
    },
    "metadata_placeholder": {
        "title": PLACEHOLDER,
        "bookmark": PLACEHOLDER,
        "blocks": [
            ("p", "가상중학교 학부모 안내"),
            ("p", "겨울방학 방과후 수업 신청을 받습니다."),
            ("p", "신청 기간: 2026. 1. 6. ~ 1. 9."),
        ],
    },
    "placeholder_in_body": {
        "title": PLACEHOLDER,
        "blocks": [
            ("p", "양식 작성 요령"),
            ("p", PLACEHOLDER),
            ("p", "위 칸에는 실제 내용을 적는다."),
        ],
    },
}


def _png(width=4, height=4):
    """단색 PNG(외부 의존성 없음)."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _runs(text):
    """연속 공백은 text:s로 적는다(ODF 공백 접기 규칙)."""
    out, i = [], 0
    while i < len(text):
        if text[i] == " ":
            j = i
            while j < len(text) and text[j] == " ":
                j += 1
            out.append(" " if j - i == 1 else f' <text:s text:c="{j - i - 1}"/>')
            i = j
        else:
            j = i
            while j < len(text) and text[j] != " ":
                j += 1
            out.append(escape(text[i:j]))
            i = j
    return "".join(out)


def _p(text, style="Standard"):
    return f'<text:p text:style-name="{style}">{_runs(text)}</text:p>'


def _cell(spec):
    if isinstance(spec, dict):
        return spec.get("text", ""), spec.get("colspan", 1), spec.get("rowspan", 1)
    return spec, 1, 1


def _paras(text):
    return text if isinstance(text, list) else ([text] if text else [])


def _table_grid(header, rows):
    """행마다 [(셀 or None=가려진 셀)] 격자. rowspan이 가린 칸도 None으로 채운다."""
    width = len(header)
    grid, pending = [], {}
    for row in [header] + rows:
        line, it, col = [], iter(row), 0
        while col < width:
            if pending.get(col, 0) > 0:
                pending[col] -= 1
                line.append(None)
                col += 1
                continue
            text, cs, rs = _cell(next(it))
            line.append((text, cs, rs))
            for k in range(cs):
                if rs > 1:
                    pending[col + k] = rs - 1
                if k:
                    line.append(None)
            col += cs
        grid.append(line)
    return grid


def _content(spec):
    body, images, tno = [], [], 0
    for block in spec["blocks"]:
        kind = block[0]
        if kind == "h":
            body.append(f'<text:h text:outline-level="{block[1]}">{_runs(block[2])}</text:h>')
        elif kind == "p":
            body.append(_p(block[1]))
        elif kind == "textbox":
            inner = "".join(_p(t) for t in block[1])
            body.append('<text:p text:style-name="Standard"><draw:frame draw:name="글상자" text:anchor-type="paragraph" '
                        f'svg:width="8cm" svg:height="1.5cm"><draw:text-box>{inner}</draw:text-box></draw:frame></text:p>')
        elif kind == "image":
            name, alt = block[1], block[2]
            images.append(name)
            body.append('<text:p text:style-name="Standard"><draw:frame draw:name="그림" text:anchor-type="as-char" '
                        f'svg:width="4cm" svg:height="4cm"><draw:image xlink:href="Pictures/{name}" xlink:type="simple" '
                        f'xlink:show="embed" xlink:actuate="onLoad"/><svg:title>{escape(alt)}</svg:title></draw:frame></text:p>')
        elif kind == "table":
            tno += 1
            t = block[1]
            grid = _table_grid(t["header"], t["rows"])
            xml = [f'<table:table table:name="표{tno}">',
                   f'<table:table-column table:number-columns-repeated="{len(t["header"])}"/>']
            for r, line in enumerate(grid):
                if r == 0:
                    xml.append("<table:table-header-rows>")
                xml.append("<table:table-row>")
                for cell in line:
                    if cell is None:
                        xml.append("<table:covered-table-cell/>")
                        continue
                    text, cs, rs = cell
                    attrs = (f' table:number-columns-spanned="{cs}"' if cs > 1 else "") + \
                            (f' table:number-rows-spanned="{rs}"' if rs > 1 else "")
                    inner = "".join(_p(x) for x in _paras(text)) or "<text:p/>"
                    xml.append(f'<table:table-cell office:value-type="string"{attrs}>{inner}</table:table-cell>')
                xml.append("</table:table-row>")
                if r == 0:
                    xml.append("</table:table-header-rows>")
            xml.append("</table:table>")
            body.append("".join(xml))
    if spec.get("bookmark"):
        body.insert(0, f'<text:p text:style-name="Standard"><text:bookmark text:name={quoteattr(spec["bookmark"])}/></text:p>')
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {NS}>'
           f'<office:body><office:text>{"".join(body)}</office:text></office:body></office:document-content>')
    return xml, images


def _styles(spec):
    parts = []
    if spec.get("header"):
        parts.append(f'<style:header>{_p(spec["header"])}</style:header>')
    if spec.get("footer"):
        parts.append(f'<style:footer>{_p(spec["footer"])}</style:footer>')
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-styles {NS}>'
            '<office:styles><style:style style:name="Standard" style:family="paragraph"/></office:styles>'
            '<office:automatic-styles><style:page-layout style:name="pm1"/></office:automatic-styles>'
            f'<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="pm1">{"".join(parts)}'
            '</style:master-page></office:master-styles></office:document-styles>')


def _meta(spec):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-meta {NS}><office:meta>'
            f'<meta:generator>docparse make_odt_fixtures</meta:generator><dc:title>{escape(spec["title"])}</dc:title>'
            '</office:meta></office:document-meta>')


def _manifest(images):
    entries = ['<manifest:file-entry manifest:full-path="/" manifest:version="1.3" '
               'manifest:media-type="application/vnd.oasis.opendocument.text"/>']
    for name in ("content.xml", "styles.xml", "meta.xml"):
        entries.append(f'<manifest:file-entry manifest:full-path="{name}" manifest:media-type="text/xml"/>')
    for name in images:
        entries.append(f'<manifest:file-entry manifest:full-path="Pictures/{name}" manifest:media-type="image/png"/>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<manifest:manifest '
            'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
            f'{"".join(entries)}</manifest:manifest>')


def reference_markdown(spec):
    """이상적인 파싱 결과. 병합 셀이 있는 표는 HTML, 없으면 파이프 표. 이미지는 대체텍스트만 남긴다."""
    lines = []
    for block in spec["blocks"]:
        kind = block[0]
        if kind == "h":
            lines.append("#" * block[1] + " " + block[2])
        elif kind == "p":
            lines.append(block[1])
        elif kind == "textbox":
            lines.extend(block[1])
        elif kind == "image":
            lines.append(f"![{block[2]}](Pictures/{block[1]})")
        elif kind == "table":
            t = block[1]
            spans = any(isinstance(c, dict) for row in t["rows"] for c in row)
            if spans:
                lines.append("<table>")
                for r, row in enumerate([t["header"]] + t["rows"]):
                    tag = "th" if r == 0 else "td"
                    cells = []
                    for c in row:
                        text, cs, rs = _cell(c)
                        attrs = (f' colspan="{cs}"' if cs > 1 else "") + (f' rowspan="{rs}"' if rs > 1 else "")
                        cells.append(f"<{tag}{attrs}>{'<br>'.join(_paras(text))}</{tag}>")
                    lines.append("<tr>" + "".join(cells) + "</tr>")
                lines.append("</table>")
            else:
                lines.append("| " + " | ".join(t["header"]) + " |")
                lines.append("|" + " --- |" * len(t["header"]))
                for row in t["rows"]:
                    lines.append("| " + " | ".join("<br>".join(_paras(_cell(c)[0])) for c in row) + " |")
        lines.append("")
    return "\n".join(lines)


def build(name, out_dir):
    spec = FIXTURES[name]
    content, images = _content(spec)
    path = Path(out_dir) / f"{name}.odt"
    with zipfile.ZipFile(path, "w") as zf:
        def put(arc, data, method=zipfile.ZIP_DEFLATED):
            info = zipfile.ZipInfo(arc, ZIP_TIME)
            info.compress_type = method
            zf.writestr(info, data)
        put("mimetype", "application/vnd.oasis.opendocument.text", zipfile.ZIP_STORED)
        put("content.xml", content)
        put("styles.xml", _styles(spec))
        put("meta.xml", _meta(spec))
        for img in images:
            put(f"Pictures/{img}", _png(), zipfile.ZIP_STORED)
        put("META-INF/manifest.xml", _manifest(images))
    (Path(out_dir) / f"{name}.reference.md").write_text(reference_markdown(spec), encoding="utf-8")
    return path


def main(argv):
    if argv[:1] == ["--list"]:
        print("\n".join(FIXTURES))
        return 0
    if not argv or argv[0].startswith("-"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    out_dir, names = Path(argv[0]), argv[1:] or list(FIXTURES)
    unknown = [n for n in names if n not in FIXTURES]
    if unknown:
        print(f"알 수 없는 자료: {', '.join(unknown)} (--list로 확인)", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        print(build(name, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
