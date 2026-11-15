"""anthropic_parse.py: 인자·응답 해석·실패 계약(네트워크·SDK 없이 가짜 클라이언트로)."""
import sys
import types
from types import SimpleNamespace as NS

import pytest

from _load import load

P = load("parsers/anthropic_parse.py", "anthropic_parse")


def msg(*blocks, stop="end_turn", model="claude-opus-5-5", tokens=10, **extra):
    return NS(content=list(blocks), stop_reason=stop, model=model, usage=NS(output_tokens=tokens), **extra)


def text(s):
    return NS(type="text", text=s)


# --- 인자 ---

def test_defaults_follow_official_guidance():
    path, opts = P.parse_args(["a.pdf"])
    assert path == "a.pdf"
    assert opts == {"model": "claude-opus-5-5", "effort": "medium", "pages_per_call": 8,
                    "max_output": 64000, "fallback": True, "suffix": ""}


@pytest.mark.parametrize("argv", [
    ["a.pdf", "b.pdf"], ["--unknown"], ["--model"], ["--model", "--effort", "high"],
    ["a.pdf", "--effort", "none"], ["a.pdf", "--pages-per-call", "-1"], ["a.pdf", "--pages-per-call", "x"],
    ["a.pdf", "--max-output", "100"], ["a.pdf", "--max-output", "200000"], ["a.pdf", "--suffix", "../x"],
])
def test_bad_arguments_are_rejected(argv):
    with pytest.raises(ValueError):
        P.parse_args(argv)


# --- 응답 해석 ---

def test_text_blocks_are_joined_and_thinking_is_skipped():
    body, served, swapped, tokens = P.message_markdown(msg(NS(type="thinking", thinking=""), text("# 제목"), text("본문")))
    assert (body, served, swapped, tokens) == ("# 제목\n본문", "claude-opus-5-5", False, 10)


def test_only_text_after_last_fallback_block_is_kept():
    m = msg(text("쓰다 만 조각"), NS(type="fallback"), text("대체 모델 본문"), model="claude-opus-4-8")
    assert P.message_markdown(m)[:3] == ("대체 모델 본문", "claude-opus-4-8", True)


def test_fallback_without_block_is_seen_in_usage_iterations():
    """요청 모델이 돌지 않고 바로 넘어가면 fallback 블록도 없고 model도 요청값일 수 있다."""
    m = msg(text("본문"))
    m.usage.iterations = [NS(type="fallback_message")]
    assert P.message_markdown(m)[2] is True


@pytest.mark.parametrize("stop,needle", [("max_tokens", "max_tokens"), ("refusal", "거부"), ("pause_turn", "미완료"), (None, "미완료")])
def test_incomplete_responses_raise(stop, needle):
    with pytest.raises(RuntimeError, match=needle):
        P.message_markdown(msg(text("부분"), stop=stop, stop_details=NS(category="cyber")))


def test_wrapping_fence_is_stripped_but_inner_code_blocks_survive():
    assert P.strip_fence("```markdown\n# 제목\n```") == "# 제목"
    inner = "```py\na\n```\n글\n```py\nb\n```"
    assert P.strip_fence(inner) == inner


# --- 요청 조립 ---

class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def fake_client(calls, message=None):
    def stream(kind):
        def run(**kwargs):
            calls.append((kind, kwargs))
            return FakeStream(message or msg(text("ok")))
        return run
    return NS(messages=NS(stream=stream("stable")), beta=NS(messages=NS(stream=stream("beta"))))


def test_fallback_goes_through_beta_only_for_supported_models():
    calls = []
    block = {"type": "image"}
    P.call_api(fake_client(calls), block, {"model": "claude-opus-5-5", "effort": "medium", "max_output": 2048, "fallback": True})
    P.call_api(fake_client(calls), block, {"model": "claude-haiku-5-5", "effort": "low", "max_output": 2048, "fallback": True})
    P.call_api(fake_client(calls), block, {"model": "claude-opus-5-5", "effort": "medium", "max_output": 2048, "fallback": False})
    kinds = [k for k, _ in calls]
    assert kinds == ["beta", "stable", "stable"]
    first = calls[0][1]
    assert first["fallbacks"] == "default" and first["betas"] == [P.FALLBACK_BETA]
    assert "fallbacks" not in calls[1][1] and "thinking" not in first and "temperature" not in first
    # 공식 권고: 문서·이미지를 글보다 앞에.
    content = first["messages"][0]["content"]
    assert content[0] is block and content[1]["type"] == "text"
    assert first["output_config"] == {"effort": "medium"} and first["max_tokens"] == 2048


def test_image_becomes_base64_image_block_and_oversize_is_refused(tmp_path, monkeypatch):
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG data")
    chunks, errors = P.build_chunks(str(png), ".png", {"pages_per_call": 8})
    assert not errors and chunks[0][1]["source"] == {"type": "base64", "media_type": "image/png", "data": "iVBORyBkYXRh"}
    monkeypatch.setattr(P, "MAX_IMAGE_BYTES", 3)
    chunks, errors = P.build_chunks(str(png), ".png", {"pages_per_call": 8})
    assert not chunks and "10MB" in errors[0]


def test_whole_pdf_is_one_document_block_when_split_is_off(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    chunks, errors = P.build_chunks(str(pdf), ".pdf", {"pages_per_call": 0})
    assert not errors and len(chunks) == 1
    label, block = chunks[0]
    assert label == "전체" and block["type"] == "document" and block["source"]["media_type"] == "application/pdf"


# --- main 실패 계약 ---

def install_fake_sdk(monkeypatch, client):
    class APIError(Exception):
        message = "boom"

    class APIStatusError(APIError):
        status_code = 500

    names = ["AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError", "BadRequestError"]
    mod = types.ModuleType("anthropic")
    mod.APIError, mod.APIStatusError = APIError, APIStatusError
    for n in names:
        setattr(mod, n, type(n, (APIStatusError,), {}))
    mod.APIConnectionError = type("APIConnectionError", (APIError,), {})
    def make(api_key, base_url):
        assert base_url == "https://api.anthropic.com"  # 환경의 ANTHROPIC_BASE_URL을 따르지 않는다
        return client
    mod.Anthropic = make
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return mod


def run_main(monkeypatch, tmp_path, argv, client, key="ANTHROPIC_API_KEY_DOCPARSE"):
    for k in P.KEY_ENVS:
        monkeypatch.delenv(k, raising=False)
    if key:
        monkeypatch.setenv(key, "fixture")
    install_fake_sdk(monkeypatch, client)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["anthropic_parse.py", *argv])
    return P.main()


def test_main_writes_output_and_marks_fallback_model(monkeypatch, tmp_path, capsys):
    (tmp_path / "문서.png").write_bytes(b"img")
    calls = []
    client = fake_client(calls, msg(text("# 한국어 본문"), model="claude-opus-4-8"))
    assert run_main(monkeypatch, tmp_path, ["문서.png"], client, key="ANTHROPIC_API_KEY") == 0
    out = (tmp_path / "문서_anthropic.md").read_text(encoding="utf-8")
    assert out == "<!-- 이미지 · 대체 모델 claude-opus-4-8 -->\n\n# 한국어 본문"
    assert "claude-opus-4-8가 대신 처리" in capsys.readouterr().out


@pytest.mark.parametrize("message", [msg(text("잘린 본문"), stop="max_tokens"), msg(text("   "))])
def test_main_leaves_no_output_on_truncation_or_empty(monkeypatch, tmp_path, message):
    (tmp_path / "a.png").write_bytes(b"img")
    (tmp_path / "a_anthropic.md").write_text("이전 결과", encoding="utf-8")
    assert run_main(monkeypatch, tmp_path, ["a.png"], fake_client([], message)) == 1
    assert not (tmp_path / "a_anthropic.md").exists()


def test_suffix_keeps_two_readings_apart(monkeypatch, tmp_path):
    (tmp_path / "a.png").write_bytes(b"img")
    assert run_main(monkeypatch, tmp_path, ["a.png", "--suffix", "opus"], fake_client([])) == 0
    assert run_main(monkeypatch, tmp_path, ["a.png", "--suffix", "sonnet"], fake_client([])) == 0
    assert sorted(p.name for p in tmp_path.glob("*.md")) == ["a_anthropic-opus.md", "a_anthropic-sonnet.md"]


def test_broken_pdf_is_reported_without_traceback(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"not a pdf")
    chunks, errors = P.build_chunks(str(pdf), ".pdf", {"pages_per_call": 8})
    assert not chunks and errors[0].startswith("오류:")


def test_main_checks_file_and_key_before_sdk(monkeypatch, tmp_path, capsys):
    assert run_main(monkeypatch, tmp_path, ["없음.pdf"], None) == 1
    assert run_main(monkeypatch, tmp_path, ["a.docx"], None) == 1
    (tmp_path / "a.png").write_bytes(b"img")
    assert run_main(monkeypatch, tmp_path, ["a.png"], None, key=None) == 1
    assert "ANTHROPIC_API_KEY_DOCPARSE" in capsys.readouterr().out
