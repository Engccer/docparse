"""azure_parse.py: 인자·요청 URL·폴링·실패 계약(네트워크 없이 request를 바꿔 끼운다)."""
import json
import sys
import urllib.parse

import pytest

from _load import load

P = load("parsers/azure_parse.py", "azure_parse")
ENDPOINT = "https://unit.cognitiveservices.azure.com/"
OP = "https://unit.cognitiveservices.azure.com/documentintelligence/documentModels/prebuilt-layout/analyzeResults/r1?api-version=2024-11-30"


def opts(**over):
    return {"model": "prebuilt-layout", "features": [], "pages": None, "locale": None, "json": False, **over}


# --- 인자 ---

def test_defaults_and_feature_merging():
    assert P.parse_args(["a.pdf"]) == ("a.pdf", opts())
    _, o = P.parse_args(["a.pdf", "--high-res", "--features", "formulas, ocrHighResolution", "--json", "--pages", "1-3,5"])
    assert o["features"] == ["ocrHighResolution", "formulas"] and o["json"] and o["pages"] == "1-3,5"


@pytest.mark.parametrize("argv", [
    ["a.pdf", "b.pdf"], ["--unknown"], ["--model"], ["a.pdf", "--model", "prebuilt-invoice"],
    ["a.pdf", "--features", "ocr.highResolution"], ["a.pdf", "--pages", "1;2"], ["a.pdf", "--locale", "--json"],
])
def test_bad_arguments_are_rejected(argv):
    with pytest.raises(ValueError):
        P.parse_args(argv)


# --- 요청 URL ---

def query_of(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_layout_url_asks_for_markdown_on_ga_version():
    url = P.analyze_url(ENDPOINT, opts(features=["ocrHighResolution"], pages="2", locale="ko"))
    assert url.startswith("https://unit.cognitiveservices.azure.com/documentintelligence/documentModels/prebuilt-layout:analyze?")
    assert query_of(url) == {"api-version": "2024-11-30", "outputContentFormat": "markdown",
                             "features": "ocrHighResolution", "pages": "2", "locale": "ko"}


def test_read_model_does_not_ask_for_markdown():
    assert query_of(P.analyze_url(ENDPOINT.rstrip("/"), opts(model="prebuilt-read"))) == {"api-version": "2024-11-30"}


# --- 폴링 ---

def fake_request(monkeypatch, polls, op_url=OP):
    seen = []

    def request(url, api_key, body=None):
        seen.append((url, api_key, body))
        if body is not None:
            return b"", {"Operation-Location": op_url}
        return json.dumps(polls.pop(0)).encode(), {}

    monkeypatch.setattr(P, "request", request)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return seen


def test_analyze_posts_base64_then_polls_until_succeeded(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    seen = fake_request(monkeypatch, [{"status": "running"}, {"status": "succeeded", "analyzeResult": {"content": "x"}}])
    assert P.analyze(str(f), ENDPOINT, "k", opts()) == {"content": "x"}
    assert json.loads(seen[0][2]) == {"base64Source": "JVBERg=="}
    assert [u for u, _, _ in seen[1:]] == [OP, OP]


@pytest.mark.parametrize("status", ["failed", "canceled"])
def test_failed_analysis_raises(monkeypatch, tmp_path, status):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    fake_request(monkeypatch, [{"status": status, "error": {"code": "InvalidContent"}}])
    with pytest.raises(RuntimeError, match="InvalidContent"):
        P.analyze(str(f), ENDPOINT, "k", opts())


def test_key_is_not_sent_to_a_foreign_operation_host(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    seen = fake_request(monkeypatch, [], op_url="https://evil.example.com/r1")
    with pytest.raises(RuntimeError, match="호스트"):
        P.analyze(str(f), ENDPOINT, "k", opts())
    assert len(seen) == 1


def test_mixed_case_endpoint_host_still_matches(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    fake_request(monkeypatch, [{"status": "succeeded", "analyzeResult": {"content": "x"}}])
    assert P.analyze(str(f), "https://Unit.cognitiveservices.azure.com/", "k", opts()) == {"content": "x"}


def test_non_json_poll_response_raises_runtime_error(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    monkeypatch.setattr(P, "request", lambda url, key, body=None: (b"<html>", {"Operation-Location": OP}))
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="해석"):
        P.analyze(str(f), ENDPOINT, "k", opts())


def test_analyze_post_is_not_resent_after_timeout(monkeypatch):
    sent = []

    def urlopen(req, timeout):
        sent.append(req.data)
        raise TimeoutError("timed out")

    monkeypatch.setattr(P.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        P.request("https://unit.example.com/x", "k", b"{}")
    assert len(sent) == 1
    with pytest.raises(RuntimeError):
        P.request("https://unit.example.com/x", "k")
    assert len(sent) == 1 + P.RETRY_MAX


def test_key_and_endpoint_are_taken_as_a_pair(monkeypatch, tmp_path, capsys):
    (tmp_path / "a.png").write_bytes(b"img")
    for k in P.KEY_ENVS + P.ENDPOINT_ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AZURE_DOCINTEL_API_KEY_DOCPARSE", "k1")
    monkeypatch.setenv("DOCUMENTINTELLIGENCE_ENDPOINT", ENDPOINT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["azure_parse.py", "a.png"])
    assert P.main() == 1
    assert "AZURE_DOCINTEL_ENDPOINT_DOCPARSE" in capsys.readouterr().out


def test_retry_after_is_clamped():
    assert P.retry_after({"Retry-After": "5"}, 2) == 5
    assert P.retry_after({"Retry-After": "9999"}, 2) == 60
    assert P.retry_after({}, 2) == 2 and P.retry_after({"Retry-After": "soon"}, 2) == 2


# --- 쪽수·confidence ---

def test_expected_pages_follows_pages_option():
    assert P.expected_pages(10, None) == 10
    assert P.expected_pages(10, "1-3,5,9-12") == 6
    assert P.expected_pages(10, "a-b") is None


def test_confidence_report_lists_low_words_and_ignores_weak_handwriting_flags():
    result = {"pages": [{"pageNumber": 2, "words": [{"content": "가", "confidence": 0.99}, {"content": "8O", "confidence": 0.5}]}],
              "styles": [{"isHandwritten": True, "confidence": 0.3}, {"isHandwritten": True, "confidence": 0.9}]}
    n, mean, low, handwritten = P.confidence_report(result)
    assert (n, round(mean, 3), low, handwritten) == (2, 0.745, [(2, "8O", 0.5)], 1)


# --- main 실패 계약 ---

def run_main(monkeypatch, tmp_path, argv, result=None, error=None, env=True):
    for k in P.KEY_ENVS + P.ENDPOINT_ENVS:
        monkeypatch.delenv(k, raising=False)
    if env:
        monkeypatch.setenv("AZURE_DOCINTEL_API_KEY_DOCPARSE", "fixture")
        monkeypatch.setenv("AZURE_DOCINTEL_ENDPOINT_DOCPARSE", ENDPOINT)

    def analyze(path, endpoint, api_key, o):
        if error:
            raise RuntimeError(error)
        return result

    monkeypatch.setattr(P, "analyze", analyze)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["azure_parse.py", *argv])
    return P.main()


def test_main_writes_markdown_and_json(monkeypatch, tmp_path):
    (tmp_path / "문서.png").write_bytes(b"img")
    result = {"content": "# 제목\n\n<table></table>", "pages": [{"pageNumber": 1, "words": []}], "tables": [{}]}
    assert run_main(monkeypatch, tmp_path, ["문서.png", "--json"], result) == 0
    assert (tmp_path / "문서_azure.md").read_text(encoding="utf-8") == "# 제목\n\n<table></table>"
    assert json.loads((tmp_path / "문서_azure.json").read_text(encoding="utf-8"))["tables"] == [{}]


def test_main_refuses_truncated_pdf(monkeypatch, tmp_path, capsys):
    """무료 등급이 처음 2쪽만 처리한 결과를 완료본으로 남기지 않는다."""
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "a_azure.md").write_text("이전 결과", encoding="utf-8")
    monkeypatch.setattr(P, "pdf_page_count", lambda path: 5)
    result = {"content": "앞 2쪽", "pages": [{}, {}]}
    assert run_main(monkeypatch, tmp_path, ["a.pdf"], result) == 1
    assert not (tmp_path / "a_azure.md").exists()
    assert "처음 2쪽" in capsys.readouterr().out
    assert run_main(monkeypatch, tmp_path, ["a.pdf", "--pages", "1-2"], result) == 0


@pytest.mark.parametrize("result,error", [({"content": "  ", "pages": [{}]}, None), (None, "HTTP 401 denied")])
def test_main_leaves_no_output_on_empty_or_error(monkeypatch, tmp_path, result, error):
    (tmp_path / "a.png").write_bytes(b"img")
    assert run_main(monkeypatch, tmp_path, ["a.png"], result, error) == 1
    assert list(tmp_path.glob("*_azure.*")) == []


def test_main_checks_inputs_before_calling(monkeypatch, tmp_path, capsys):
    (tmp_path / "a.docx").write_bytes(b"PK")
    assert run_main(monkeypatch, tmp_path, ["a.hwpx"]) == 1
    assert run_main(monkeypatch, tmp_path, ["a.docx", "--high-res"]) == 1
    assert run_main(monkeypatch, tmp_path, ["a.docx", "--pages", "1"]) == 1
    assert run_main(monkeypatch, tmp_path, ["a.docx"], env=False) == 1
    out = capsys.readouterr().out
    assert "AZURE_DOCINTEL_API_KEY_DOCPARSE" in out and "AZURE_DOCINTEL_ENDPOINT_DOCPARSE" in out
