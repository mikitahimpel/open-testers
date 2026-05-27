from pathlib import Path

import pytest

from open_testers.schema import (
    ActStep,
    AssertStep,
    FilesStep,
    LoginStep,
    ScreenshotStep,
    TestDefinition,
    load,
)

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "example.yaml"


def test_load_bundled_example():
    t = load(EXAMPLE)
    assert isinstance(t, TestDefinition)
    assert t.title == "Hacker News front page smoke test"
    assert t.platform == "web"
    assert len(t.steps) == 3
    assert isinstance(t.steps[0], ActStep)
    assert isinstance(t.steps[1], ScreenshotStep)
    assert isinstance(t.steps[2], AssertStep)


def test_all_five_step_types_parse(tmp_path: Path):
    yaml_text = """
title: All step types
platform: web
projectUrl: https://example.com
steps:
  - {type: act, title: do thing}
  - {type: assert, title: check thing}
  - {type: login, title: sign in, credentialId: cred-abc, temporaryEmail: false}
  - {type: files, title: upload, fileIds: [file-1, file-2]}
  - {type: screenshot, title: snap}
"""
    p = tmp_path / "all.yaml"
    p.write_text(yaml_text)
    t = load(p)

    assert [s.type for s in t.steps] == [
        "act",
        "assert",
        "login",
        "files",
        "screenshot",
    ]

    login = t.steps[2]
    assert isinstance(login, LoginStep)
    assert login.credentialId == "cred-abc"
    assert login.temporaryEmail is False

    files = t.steps[3]
    assert isinstance(files, FilesStep)
    assert files.fileIds == ["file-1", "file-2"]


def test_unknown_step_type_is_rejected(tmp_path: Path):
    yaml_text = """
title: bad
steps:
  - {type: bogus, title: oops}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(yaml_text)
    with pytest.raises(Exception):
        load(p)


def test_files_step_requires_file_ids(tmp_path: Path):
    yaml_text = """
title: missing fileIds
steps:
  - {type: files, title: upload}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(yaml_text)
    with pytest.raises(Exception):
        load(p)
