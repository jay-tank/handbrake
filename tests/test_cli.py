import json

from cli import main

_UNGATED = (
    "from langchain.agents import AgentExecutor\n"
    "from langchain_core.tools import tool\n"
    "@tool\n"
    "def delete_user(uid):\n"
    "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
    "def build(agent):\n"
    "    return AgentExecutor(agent=agent, tools=[delete_user])\n"
)
_GATED = (
    "from langchain.agents import AgentExecutor\n"
    "from langchain_core.tools import tool\n"
    "@tool\n"
    "def delete_user(uid, require_approval=True):\n"
    "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
    "def build(agent):\n"
    "    return AgentExecutor(agent=agent, tools=[delete_user], require_approval=True)\n"
)
_WARN = (
    "from langchain_core.tools import tool\n"
    "@tool\n"
    "def deploy_service(name):\n"
    "    subprocess.run(['kubectl', 'apply', name])\n"
)


def run(args, capsys):
    code = main(args)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_exit_1_on_blocker(capsys, tmp_path):
    f = tmp_path / "bad.py"
    f.write_text(_UNGATED)
    code, out, err = run([str(f), "--no-color"], capsys)
    assert code == 1
    assert "BLOCKER" in out
    assert "HB001" in out


def test_exit_0_on_clean_file(capsys, tmp_path):
    f = tmp_path / "good.py"
    f.write_text(_GATED)
    code, out, err = run([str(f), "--no-color"], capsys)
    assert code == 0
    assert "no ungated destructive agent tools" in out


def test_exit_2_when_no_paths(capsys):
    code, out, err = run([], capsys)
    assert code == 2
    assert "no paths given" in err


def test_exit_2_when_no_source_files(capsys, tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    code, out, err = run([str(tmp_path)], capsys)
    assert code == 2
    assert "no scannable source" in err


def test_json_output_shape(capsys, tmp_path):
    f = tmp_path / "bad.py"
    f.write_text(_UNGATED)
    code, out, err = run([str(f), "--json"], capsys)
    assert code == 1
    data = json.loads(out)
    assert data["files_scanned"] == 1
    assert data["summary"]["total"] == len(data["findings"])
    assert data["summary"]["blockers"] >= 1
    first = data["findings"][0]
    assert {"file", "line", "col", "rule", "severity", "message", "fix"} <= set(first)


def test_warning_only_exits_0_without_strict_and_1_with_strict(capsys, tmp_path):
    f = tmp_path / "cv.py"
    f.write_text(_WARN)
    code, out, err = run([str(f), "--no-color"], capsys)
    assert code == 0  # HB002 warning alone does not fail by default
    code, out, err = run([str(f), "--no-color", "--strict"], capsys)
    assert code == 1  # --strict promotes warnings to a failure


def test_exclude_glob_skips_paths(capsys, tmp_path):
    (tmp_path / "bad.py").write_text(_UNGATED)
    code, out, err = run([str(tmp_path), "--exclude", "*bad.py"], capsys)
    assert code == 2  # the only match was excluded -> nothing scannable
    assert "no scannable source" in err


def test_directory_scanned_recursively_skips_node_modules(capsys, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text(_UNGATED)
    vend = tmp_path / "node_modules"
    vend.mkdir()
    (vend / "b.py").write_text(_UNGATED)
    code, out, err = run([str(tmp_path), "--json"], capsys)
    assert code == 1
    data = json.loads(out)
    assert data["files_scanned"] == 1  # node_modules skipped


def test_syntax_error_file_is_skipped_not_crashed(capsys, tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def build(agent, tools)\n    return 1\n")  # missing colon
    code, out, err = run([str(f)], capsys)
    assert code == 2
    assert "could not parse" in err


def test_bundled_examples_ungated_and_gated(capsys):
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ungated = os.path.join(root, "examples", "ungated.py")
    gated = os.path.join(root, "examples", "gated.py")
    assert run([ungated, "--json"], capsys)[0] == 1
    assert run([gated, "--no-color"], capsys)[0] == 0
