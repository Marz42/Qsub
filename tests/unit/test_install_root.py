"""install_root resolution tests."""

from __future__ import annotations

from pathlib import Path

from qsub_core import config


def test_install_root_respects_env(tmp_path: Path, monkeypatch):
    marker = tmp_path / "manifests"
    marker.mkdir()
    (marker / "runtime-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("QSUB_ROOT", str(tmp_path))
    config.install_root.cache_clear()
    assert config.install_root() == tmp_path.resolve()
    config.install_root.cache_clear()


def test_bundled_bin_dir_under_root(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("QSUB_ROOT", str(tmp_path))
    config.install_root.cache_clear()
    assert config.bundled_bin_dir() == tmp_path.resolve() / "bin"
    config.install_root.cache_clear()
