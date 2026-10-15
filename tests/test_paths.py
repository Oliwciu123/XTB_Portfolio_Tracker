"""Portable / frozen path helpers."""

from __future__ import annotations

from pathlib import Path

from xtb_analyzer.paths import app_writable_root, asset_path, ensure_app_cwd, is_frozen


def test_not_frozen_in_normal_pytest():
    assert is_frozen() is False


def test_writable_root_is_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    root = app_writable_root()
    assert root == tmp_path.resolve()


def test_assets_exist():
    ico = asset_path("assets", "app.ico")
    png = asset_path("assets", "app.png")
    assert ico.is_file()
    assert png.is_file()


def test_ensure_app_cwd_changes_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    root = ensure_app_cwd()
    assert Path.cwd() == root
