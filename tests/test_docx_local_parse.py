"""DOCX 검증은 XML 접두사·직렬화 표기에 의존하지 않는다."""
import hashlib
import zipfile

import pytest
from _load import load

D = load("parsers/docx_local_parse.py", "docx_local_parse")
WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MATH = "http://schemas.openxmlformats.org/officeDocument/2006/math"


@pytest.mark.parametrize("prefix", ["", "alias:"])
def test_loss_markers_use_namespace_identity(prefix):
    declaration = "xmlns" if not prefix else "xmlns:alias"
    for uri, tag, expected in ((WORD, "sym", (1, 0, 0)), (MATH, "oMath", (0, 1, 0)), (WORD, "drawing", (0, 0, 1))):
        xml = f'<{prefix}{tag} {declaration}="{uri}"></{prefix}{tag}>'
        assert D._count_silent_loss_markers(xml) == expected


def test_same_local_names_in_other_namespaces_are_not_gate_markers():
    xml = '<root xmlns:w="urn:other" xmlns:m="urn:other"><w:sym value="x"/><m:oMath></m:oMath><w:drawing></w:drawing></root>'
    assert D._count_silent_loss_markers(xml) == (0, 0, 0)


@pytest.mark.parametrize("part", ["body", "header"])
def test_renamed_math_prefix_blocks_output_and_preserves_source(tmp_path, part, monkeypatch):
    docx = pytest.importorskip("docx")
    from lxml import etree
    source = tmp_path / "equation.docx"
    doc = docx.Document()
    paragraph = doc.add_paragraph("본문") if part == "body" else doc.sections[0].header.paragraphs[0]
    paragraph._p.append(etree.fromstring(f'<m:oMath xmlns:m="{MATH}"><m:r><m:t>x=42</m:t></m:r></m:oMath>'))
    doc.save(source)
    with zipfile.ZipFile(source) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    for name, content in contents.items():
        if name.endswith(".xml"):
            contents[name] = content.replace(b"xmlns:m=", b"xmlns:math=").replace(b"<m:", b"<math:").replace(b"</m:", b"</math:").replace(b" m:", b" math:")
    with zipfile.ZipFile(source, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "result.md"
    monkeypatch.setattr(D, "get_output_filename", lambda _: str(output))
    assert not D.process_file(str(source))
    assert not output.exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
