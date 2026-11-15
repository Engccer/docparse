"""Isolated CLI fixture: standard library only, fake services, no external sockets."""
import json
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace


def guard(event, args):
    if event == "socket.connect" and args[1][0] in ("127.0.0.1", "::1"):
        return  # Windows asyncio uses a loopback socketpair internally.
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise AssertionError("External network disabled in CLI tests")


sys.addaudithook(guard)


def record(kind, **values):
    with Path("calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"kind": kind, **values}, ensure_ascii=False) + "\n")


def parse(**kwargs):
    source = kwargs.pop("upload_file")
    record("parse", name=Path(source.name).name, content=source.read().hex(), **kwargs)
    if os.environ.get("RESPONSE") == "error":
        raise RuntimeError("fixture API failure")
    body = "" if os.environ.get("RESPONSE") == "empty" else "# 한국어\n\n표와 숫자 12\n"
    extra = {}
    if "items" in kwargs.get("expand", []):
        extra = {"items": {"pages": [{"page_number": 4, "items": [{"type": "table", "rows": [["1/2", "90"]]}]}]},
                 "metadata": {"pages": [{"page_number": 4, "confidence": 0.91}, {"page_number": 25, "confidence": 0.42}]}}
    return SimpleNamespace(markdown_full=body, text_full="", status="COMPLETED", **extra)


def ocr(**kwargs):
    record("ocr", **kwargs)
    if os.environ.get("RESPONSE") == "error":
        raise RuntimeError("fixture API failure")
    body = " " if os.environ.get("RESPONSE") == "empty" else "한국어 본문 12"
    return SimpleNamespace(pages=[SimpleNamespace(markdown=body)])


def client(**kwargs):
    record("client")
    return SimpleNamespace(parsing=SimpleNamespace(parse=parse), ocr=SimpleNamespace(process=ocr))


def get(url, **kwargs):
    record("credits", url=url, timeout=kwargs["timeout"])
    if os.environ.get("RESPONSE") == "error":
        raise RuntimeError("fixture credit failure")
    if url.endswith("/projects"):
        body = [{"organization_id": "fixture-org"}]
    else:
        body = {
            "plan": {"name": "시험", "current_billing_period": {
                "start_date": "2026-01-01", "end_date": "2026-02-01"}},
            "usage": {"active_free_credits_usage": [{"remaining_balance": 12,
                "starting_balance": 20, "expires_at": "2026-02-01"}]},
        }
    return SimpleNamespace(json=lambda: body, raise_for_status=lambda: None)


class _Types:
    """google.genai.types 대역: 파서가 만드는 요청 모양만 받아 적는다."""
    GenerateContentConfig = ThinkingConfig = Blob = PartMediaResolution = SimpleNamespace
    PartMediaResolutionLevel = SimpleNamespace(**{f"MEDIA_RESOLUTION_{n}": n.lower()
                                                  for n in ("LOW", "MEDIUM", "HIGH", "ULTRA_HIGH")})

    class Part(SimpleNamespace):
        @classmethod
        def from_bytes(cls, data, mime_type):
            return cls(inline_data=SimpleNamespace(data=data, mime_type=mime_type), media_resolution=None)


def generate_content(model, contents, config):
    part = contents[0]
    thinking = getattr(config, "thinking_config", None)
    record("gemini", model=model, mime_type=part.inline_data.mime_type,
           media_resolution=part.media_resolution.level if part.media_resolution else None,
           thinking_level=thinking.thinking_level if thinking else None)
    return SimpleNamespace(text="| 칸 | 12 |\n", candidates=[SimpleNamespace(finish_reason="STOP")])


def genai_client(**kwargs):
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


if os.environ.get("FAKE_SDK") == "1":
    _genai = SimpleNamespace(Client=genai_client, types=_Types)
    sys.modules["google"] = SimpleNamespace(genai=_genai)
    sys.modules["google.genai"] = _genai
    sys.modules["google.genai.types"] = _Types
    sys.modules["llama_cloud"] = SimpleNamespace(Client=client)
    sys.modules["mistralai"] = SimpleNamespace()
    sys.modules["mistralai.client"] = SimpleNamespace(Mistral=client)
    sys.modules["httpx"] = SimpleNamespace(get=get)

sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
