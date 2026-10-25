"""Cloud parser CLI contracts, including actual process exit status, without SDKs."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_name("cloud_cli_runner.py")
SCRIPTS = ["llamaparse_parse.py", "mistral_parse.py"]


def invoke(tmp_path, script, *args, sdk=False, key=False, response="ok", stdin=""):
    env = {"PATH": os.defpath, "PYTHONIOENCODING": "utf-8", "RESPONSE": response}
    if "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    if sdk:
        env["FAKE_SDK"] = "1"
    if key:
        env.update(LLAMAPARSE_API_KEY="fixture", MISTRAL_API_KEY="fixture")
    return subprocess.run(
        [sys.executable, "-S", str(RUNNER), str(ROOT / "parsers" / script), *map(str, args)],
        env=env, cwd=tmp_path, input=stdin, capture_output=True,
        text=True, encoding="utf-8", timeout=20,
    )


def calls(tmp_path):
    path = tmp_path / "calls.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_without_key_or_sdk(tmp_path, script, flag):
    result = invoke(tmp_path, script, flag)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout
    assert not calls(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("script,args", [
    ("llamaparse_parse.py", ["--unknown"]),
    ("llamaparse_parse.py", ["--tier"]),
    ("llamaparse_parse.py", ["--tier", "bad"]),
    ("llamaparse_parse.py", ["--lang"]),
    ("llamaparse_parse.py", ["--lang", ""]),
    ("llamaparse_parse.py", ["--instructions"]),
    ("mistral_parse.py", ["--unknown"]),
    ("mistral_parse.py", ["문서.png", "second.png"]),
])
def test_bad_arguments_are_rejected_before_sdk(tmp_path, script, args):
    (tmp_path / "문서.png").write_bytes(b"image")
    result = invoke(tmp_path, script, *args, sdk=True, key=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not calls(tmp_path)


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("kind", ["missing", "directory", "unsupported", "no-input"])
def test_input_validation_precedes_sdk(tmp_path, script, kind):
    path = tmp_path / ("문서.invalid" if kind == "unsupported" else "문서.pdf")
    if kind == "directory":
        path.mkdir()
    elif kind == "unsupported":
        path.write_bytes(b"input")
    args = [] if kind == "no-input" else [path]
    result = invoke(tmp_path, script, *args, sdk=True, key=True)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not calls(tmp_path)


@pytest.mark.parametrize("prefix", [[], ["--credits"]])
def test_llama_validates_entire_explicit_batch_before_any_request(tmp_path, prefix):
    source = tmp_path / "문서.txt"
    source.write_text("원본", encoding="utf-8")
    result = invoke(tmp_path, SCRIPTS[0], *prefix, source, "missing.pdf", sdk=True, key=True)
    assert result.returncode != 0
    assert not calls(tmp_path)
    assert not (tmp_path / "문서_llamaparse.md").exists()


@pytest.mark.parametrize("kind", ["missing", "empty", "directory", "empty-path"])
def test_llama_invalid_instructions_before_api(tmp_path, kind):
    source = tmp_path / "문서.txt"
    source.write_text("원본", encoding="utf-8")
    instructions = tmp_path / "instructions.txt"
    if kind == "empty":
        instructions.write_text(" \n", encoding="utf-8")
    elif kind == "directory":
        instructions.mkdir()
    result = invoke(tmp_path, SCRIPTS[0], source, "--instructions",
                    "" if kind == "empty-path" else instructions, sdk=True, key=True)
    assert result.returncode != 0
    assert not calls(tmp_path)


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("sdk,key", [(False, True), (True, False)])
def test_missing_runtime_requirement_fails_without_request(tmp_path, script, sdk, key):
    source = tmp_path / "문서.png"
    source.write_bytes(b"image")
    result = invoke(tmp_path, script, source, sdk=sdk, key=key)
    assert result.returncode == 1
    assert not calls(tmp_path)


@pytest.mark.parametrize("tier", ["fast", "cost_effective", "agentic", "agentic_plus"])
def test_llama_options_and_utf8_output(tmp_path, tier):
    source = tmp_path / "한글 문서.txt"
    source.write_text("원본", encoding="utf-8")
    other = tmp_path / "두번째.txt"
    other.write_text("두번째 원본", encoding="utf-8")
    instructions = tmp_path / "instructions.txt"
    instructions.write_text("  표와 그림을 보존\n", encoding="utf-8")
    result = invoke(tmp_path, SCRIPTS[0], source, "--tier", tier, "--lang", "en",
                    other, "--instructions", instructions, sdk=True, key=True)
    assert result.returncode == 0, result.stdout + result.stderr
    requests = [call for call in calls(tmp_path) if call["kind"] == "parse"]
    assert [call["name"] for call in requests] == [source.name, other.name]
    for call in requests:
        assert call["tier"] == tier
        assert call["version"] == "latest"
        assert call["processing_options"] == {"ocr_parameters": {"languages": ["en"]}}
        assert call["expand"] == ["markdown_full", "text_full"]
        assert call["output_options"] == {"markdown": {"annotate_links": True,
            "tables": {"output_tables_as_markdown": True, "merge_continued_tables": True}}}
        if tier in ("agentic", "agentic_plus"):
            assert call["agentic_options"] == {"custom_prompt": "표와 그림을 보존"}
        else:
            assert "agentic_options" not in call
    for name in ("한글 문서_llamaparse.md", "두번째_llamaparse.md"):
        assert (tmp_path / name).read_text(encoding="utf-8") == "# 한국어\n\n표와 숫자 12\n"


def test_llama_credits_only_never_parses_current_directory(tmp_path):
    (tmp_path / "문서.txt").write_text("원본", encoding="utf-8")
    result = invoke(tmp_path, SCRIPTS[0], "--credits", sdk=True, key=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "12 / 20" in result.stdout
    assert [call["kind"] for call in calls(tmp_path) if call["kind"] != "client"] == ["credits", "credits"]
    assert not list(tmp_path.glob("*_llamaparse.md"))


def test_mistral_request_and_utf8_output(tmp_path):
    source = tmp_path / "한글 문서.png"
    source.write_bytes(b"image-data")
    result = invoke(tmp_path, SCRIPTS[1], source, sdk=True, key=True)
    assert result.returncode == 0, result.stdout + result.stderr
    request, = [call for call in calls(tmp_path) if call["kind"] == "ocr"]
    assert request == {"kind": "ocr", "model": "mistral-ocr-latest", "include_image_base64": True,
        "document": {"type": "document_url", "document_url": "data:image/png;base64," + base64.b64encode(b"image-data").decode()}}
    assert (tmp_path / "한글 문서_mistral.md").read_text(encoding="utf-8") == "<!-- Page 1/1 -->\n\n한국어 본문 12"


@pytest.mark.parametrize("script,suffix", [(SCRIPTS[0], "llamaparse"), (SCRIPTS[1], "mistral")])
@pytest.mark.parametrize("response", ["empty", "error"])
def test_processing_failure_is_nonzero_and_stale_output_removed(tmp_path, script, suffix, response):
    source = tmp_path / "문서.png"
    source.write_bytes(b"image")
    output = tmp_path / f"문서_{suffix}.md"
    output.write_text("이전 결과", encoding="utf-8")
    result = invoke(tmp_path, script, source, sdk=True, key=True, response=response)
    assert result.returncode == 1, result.stdout + result.stderr
    assert not output.exists()


@pytest.mark.parametrize("script,suffix", [(SCRIPTS[0], "llamaparse"), (SCRIPTS[1], "mistral")])
def test_automatic_selection_preserved(tmp_path, script, suffix):
    for name in ("b.png", "a.png"):
        (tmp_path / name).write_bytes(b"image")
    result = invoke(tmp_path, script, sdk=True, key=True, stdin="1\nY\nN\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / f"a_{suffix}.md").exists()
    assert not (tmp_path / f"b_{suffix}.md").exists()
    if suffix == "llamaparse":
        request, = [call for call in calls(tmp_path) if call["kind"] == "parse"]
        assert request["tier"] == "agentic"
        assert request["processing_options"] == {"ocr_parameters": {"languages": ["ko"]}}


def test_mistral_explicit_empty_path_does_not_autodiscover(tmp_path):
    (tmp_path / "문서.png").write_bytes(b"image")
    result = invoke(tmp_path, SCRIPTS[1], "", sdk=True, key=True)
    assert result.returncode == 1
    assert not calls(tmp_path)


def test_llama_credits_can_precede_parsing(tmp_path):
    source = tmp_path / "문서.txt"
    source.write_text("원본", encoding="utf-8")
    result = invoke(tmp_path, SCRIPTS[0], "--credits", source, sdk=True, key=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [call["kind"] for call in calls(tmp_path) if call["kind"] != "client"] == ["credits", "credits", "parse"]
    assert (tmp_path / "문서_llamaparse.md").read_text(encoding="utf-8") == "# 한국어\n\n표와 숫자 12\n"


def test_llama_credits_failure_propagates(tmp_path):
    result = invoke(tmp_path, SCRIPTS[0], "--credits", sdk=True, key=True, response="error")
    assert result.returncode == 1
    assert [call["kind"] for call in calls(tmp_path) if call["kind"] != "client"] == ["credits"]
