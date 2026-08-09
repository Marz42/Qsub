"""Regression tests for model storage, resumability, and cache lifecycle."""

from __future__ import annotations

import hashlib
from pathlib import Path

from scripts import build_runtime
from gui.paths import work_dir_for_source
from qsub_core import config
from qsub_core.model_store import validate_model_dir, write_model_marker
from qsub_core.pipeline.resume import classify_resume_change, clear_cancel_requested
from qsub_core.pipeline.workspace import create_job_workspace


def _signature(**updates) -> dict:
    value = {
        "pipeline_version": 2,
        "source_fingerprint": "media-a",
        "audio_stream": "auto",
        "language": "Chinese",
        "asr_revision": "asr-a",
        "aligner_revision": "align-a",
    }
    value.update(updates)
    return value


def test_runtime_builder_uses_uv_managed_dir_not_active_venv(tmp_path: Path, monkeypatch):
    managed_dir = tmp_path / "uv" / "python"
    older = managed_dir / "cpython-3.12.12-windows-x86_64-none"
    newer = managed_dir / "cpython-3.12.13-windows-x86_64-none"
    for root in (older, newer):
        (root / "Lib").mkdir(parents=True)
        (root / "python.exe").write_bytes(b"")
        (root / "python312.dll").write_bytes(b"")

    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / ".venv"))

    def fake_check_output(cmd, **kwargs):
        assert "VIRTUAL_ENV" not in kwargs["env"]
        if cmd == ["uv", "python", "dir"]:
            return str(managed_dir)
        executable = Path(cmd[0]).resolve()
        if executable == (older / "python.exe").resolve():
            return "3.12.12\n"
        if executable == (newer / "python.exe").resolve():
            return "3.12.13\n"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(build_runtime.subprocess, "check_output", fake_check_output)
    assert build_runtime.find_standalone_python("3.12") == (newer / "python.exe").resolve()


def test_installed_gui_launcher_is_visible_and_bypasses_vbs():
    build_source = (build_runtime.ROOT / "scripts" / "build_runtime.py").read_text(encoding="utf-8")
    installer = (build_runtime.ROOT / "packaging" / "inno" / "QwenSubtitle.iss").read_text(
        encoding="utf-8"
    )

    assert 'gui.main", 1, False' in build_source
    assert 'gui.main", 0, False' not in build_source
    assert '#define MyAppExeName "runtime\\pythonw.exe"' in installer
    assert '#define MyAppExeParameters "-I -m gui.main"' in installer
    assert 'Filename: "{app}\\{#MyAppExeName}"; Parameters: "{#MyAppExeParameters}"' in installer


def test_installer_does_not_strip_importable_testing_packages():
    installer = (build_runtime.ROOT / "packaging" / "inno" / "QwenSubtitle.iss").read_text(
        encoding="utf-8"
    )

    assert "*\\testing\\*" not in installer
    assert "*\\tests\\*" not in installer
    assert "*\\test\\*" not in installer
    assert 'Excludes: "__pycache__\\*,*.pyc,*.pyo,.pytest_cache\\*"' in installer


def test_resume_signature_invalidates_correct_stage():
    current = _signature()
    assert classify_resume_change(current, current, same_source_path=True, previous_pipeline_version=2) == "none"
    assert (
        classify_resume_change(
            current,
            _signature(source_fingerprint="media-b"),
            same_source_path=True,
            previous_pipeline_version=2,
        )
        == "media"
    )
    assert (
        classify_resume_change(
            current,
            _signature(audio_stream="2"),
            same_source_path=True,
            previous_pipeline_version=2,
        )
        == "media"
    )
    assert (
        classify_resume_change(
            current,
            _signature(asr_revision="asr-b"),
            same_source_path=True,
            previous_pipeline_version=2,
        )
        == "recognition"
    )


def test_model_validation_requires_size_hash_and_revision(tmp_path: Path):
    model = tmp_path / "model"
    model.mkdir()
    payload = b"pinned model"
    (model / "weights.bin").write_bytes(payload)
    entry = {
        "name": "test-model",
        "revision": "abc123",
        "required_files": [
            {
                "path": "weights.bin",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    write_model_marker(model, entry)
    assert validate_model_dir(model, entry, verify_hashes=True)["ok"]
    (model / "weights.bin").write_bytes(b"corrupt model")
    result = validate_model_dir(model, entry, verify_hashes=True)
    assert not result["ok"]
    assert any("size mismatch" in issue for issue in result["issues"])


def test_gui_workspace_is_stable_and_user_writable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    source = tmp_path / "movie.mkv"
    first = work_dir_for_source(source)
    second = work_dir_for_source(source)
    assert first == second
    assert first.parent == tmp_path / "QwenSubtitle" / "jobs"


def test_models_default_to_user_data_unless_oem_marker_exists(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    local = tmp_path / "local"
    (install / "models").mkdir(parents=True)
    monkeypatch.setenv("QSUB_ROOT", str(install))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    config.install_root.cache_clear()
    assert config.default_models_dir() == local / "QwenSubtitle" / "models"
    (install / "models" / ".qsub-bundled-models.json").write_text("{}", encoding="utf-8")
    assert config.default_models_dir() == install / "models"
    config.install_root.cache_clear()


def test_workspace_prunes_only_reproducible_cache(tmp_path: Path):
    ws = create_job_workspace(work_dir=tmp_path / "job")
    ws.audio_wav.write_bytes(b"wav")
    ws.probe_json.write_text("{}", encoding="utf-8")
    ws.project_json.write_text("{}", encoding="utf-8")
    ws.job_json.write_text("{}", encoding="utf-8")
    (ws.asr_dir / "000000.json").write_text("{}", encoding="utf-8")
    ws.prune_intermediates()
    assert not ws.audio_wav.exists()
    assert not ws.asr_dir.exists()
    assert ws.project_json.is_file()
    assert ws.job_json.is_file()


def test_stale_cancel_flag_is_cleared(tmp_path: Path):
    flag = tmp_path / "cancel.flag"
    flag.write_text("1", encoding="utf-8")
    clear_cancel_requested(tmp_path)
    assert not flag.exists()
