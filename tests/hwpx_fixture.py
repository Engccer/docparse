"""시험용 합성 HWPX(실명·실제 문서 없음): 밑줄 run과 밑줄 공백 빈칸을 담는다.

엔진(hwpx-tomd)이 읽는 부분만 채운다: section0.xml 본문, header.xml 글자 모양(charPr 밑줄), manifest.
charPr 0 = 밑줄 없음, 1 = 밑줄(BOTTOM).
"""
import zipfile

_SEC = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">{body}</hs:sec>'
)
_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"><hh:refList>'
    '<hh:charProperties itemCnt="2">'
    '<hh:charPr id="0" height="1000"><hh:underline type="NONE" shape="SOLID" color="#000000"/></hh:charPr>'
    '<hh:charPr id="1" height="1000"><hh:underline type="BOTTOM" shape="SOLID" color="#000000"/></hh:charPr>'
    "</hh:charProperties></hh:refList></hh:head>"
)
_MANIFEST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
    '<manifest:file-entry manifest:full-path="Contents/section0.xml" manifest:media-type="application/xml"/>'
    "</manifest:manifest>"
)


def run(cid, text):
    return f'<hp:run charPrIDRef="{cid}"><hp:t>{text}</hp:t></hp:run>'


# 영작 빈칸(공백 6칸 밑줄 run)과 어법 문항의 밑줄 구간(서식 경계로 두 run에 나뉨)
BODY = (
    "<hp:p>" + run(0, "1. 다음 빈칸에 알맞은 말을 쓰시오. I am ") + run(1, "      ") + run(0, " to school.") + "</hp:p>"
    "<hp:p>" + run(0, "2. (A) ") + run(1, "밑줄 친") + run(1, " 부분") + run(0, " 중 어법상 틀린 것은?") + "</hp:p>"
)
# 빈칸 없이 밑줄 구간만 있는 문서(장식 밑줄 또는 어법 문항만)
SPAN_ONLY = "<hp:p>" + run(0, "2. (A) ") + run(1, "밑줄 친") + run(1, " 부분") + run(0, " 중 어법상 틀린 것은?") + "</hp:p>"
# 탭으로 그은 밑줄 빈칸(엔진은 tab을 공백 한 칸으로 읽는다)
TAB_BLANK = "<hp:p>" + run(0, "Name ") + '<hp:run charPrIDRef="1"><hp:t><hp:tab/></hp:t></hp:run>' + run(0, " end") + "</hp:p>"
BLANK = "\\_" * 6
SPAN = "<u>밑줄 친 부분</u>"


def make_hwpx(path, body=BODY, header=True):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("META-INF/manifest.xml", _MANIFEST)
        zf.writestr("Contents/section0.xml", _SEC.format(body=body))
        if header:
            zf.writestr("Contents/header.xml", _HEADER)
    return path
