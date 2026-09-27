"""시험용: 저장소의 스크립트를 모듈로 읽는다(네트워크 호출 없음)."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
