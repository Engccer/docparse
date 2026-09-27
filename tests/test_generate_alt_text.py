"""generate_alt_text: --map·--output의 부모 폴더가 아직 없어도 유료 호출 뒤 결과를 잃지 않는다.

SKILL.md Step 4 명령은 `--map "_work-docparse/..."`를 쓰는데 그 폴더는 Step 8에서야 만들어진다.
generate_map(유료 Gemini 호출 자리)은 가짜로 바꿔 네트워크를 부르지 않는다.
"""
import sys

from _load import load


def test_map_and_output_parent_dirs_are_created(tmp_path, monkeypatch):
    g = load("scripts/generate_alt_text.py", "generate_alt_text")
    calls = []

    def fake_generate_map(pdf, by_page, model, dpi, tmpl):
        calls.append(1)
        return {m[2]: {"ko_alt": "흐름도"} for v in by_page.values() for m in v}, []

    monkeypatch.setattr(g, "generate_map", fake_generate_map)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "doc_llamaparse.md").write_text("x\n![diagram](page_1_image_1_v2.jpg)\n", encoding="utf-8")
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(sys, "argv", [
        "generate_alt_text.py", "--pdf", "doc.pdf", "--markdown", "doc_llamaparse.md",
        "--output", "out/doc_with_alt.md", "--map", "_work-docparse/doc_alt_map.json",
    ])
    g.main()
    assert calls == [1]
    assert (tmp_path / "_work-docparse" / "doc_alt_map.json").exists()
    assert "(이미지: 흐름도)" in (tmp_path / "out" / "doc_with_alt.md").read_text(encoding="utf-8")
