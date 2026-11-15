"""모든 실행 스크립트의 공통 진입 계약: --help는 파일로 오인하지 않고, 실행할 때만 출력을 utf-8로 고정한다."""
import ast
import os
import subprocess
import sys

import pytest

from _load import ROOT

PARSERS = sorted(p.name for p in (ROOT / "parsers").glob("*_parse.py"))
RUNNABLE = sorted(p for d in ("parsers", "scripts") for p in (ROOT / d).glob("*.py")
                  if 'if __name__ == "__main__":' in p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", PARSERS)
def test_help_exits_zero_without_touching_files(tmp_path, name):
    """콘솔 인코딩이 cp949여도 --help가 utf-8 한글 사용법을 내고 0으로 끝나며 파일을 만들지 않는다."""
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env["PYTHONIOENCODING"] = "cp949"
    result = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "parsers" / name), "--help"],
                            cwd=tmp_path, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    stdout = result.stdout.decode("utf-8")  # cp949로 나왔다면 여기서 깨진다
    assert result.returncode == 0, stdout + result.stderr.decode("utf-8", "replace")
    assert "docparse" in stdout or "usage:" in stdout
    assert any("가" <= ch <= "힣" for ch in stdout)
    assert list(tmp_path.iterdir()) == []


def _reconfigure_calls(nodes):
    return [n for node in nodes for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "reconfigure"]


@pytest.mark.parametrize("path", RUNNABLE, ids=lambda p: p.name)
def test_stdout_is_reconfigured_only_when_run(path):
    """출력 재설정은 `if __name__ == "__main__":` 안에만 둔다. import만으로 호출자의 stdout을 바꾸지 않는다."""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    guards = [n for n in body if isinstance(n, ast.If) and "__main__" in ast.dump(n.test)]
    top_level = [n for n in body if n not in guards and not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    assert _reconfigure_calls(top_level) == []
    in_functions = _reconfigure_calls([n for n in body if isinstance(n, (ast.FunctionDef, ast.ClassDef))])
    assert _reconfigure_calls(guards) or in_functions
