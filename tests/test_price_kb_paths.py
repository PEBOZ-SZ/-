from __future__ import annotations


def test_official_kb_default_uses_repo_deployed_workbook(monkeypatch) -> None:
    import price_kb_paths

    monkeypatch.delenv("PRICE_KB_OFFICIAL_PATH", raising=False)

    path = price_kb_paths.official_kb_path()

    assert path == price_kb_paths.REPO_OFFICIAL_KB_PATH.resolve()
    assert path.is_file()
    assert "data" in path.parts
    assert "knowledge_base" in path.parts


def test_official_kb_env_override_still_wins(monkeypatch, tmp_path) -> None:
    import price_kb_paths

    override = tmp_path / "custom.xlsx"
    monkeypatch.setenv("PRICE_KB_OFFICIAL_PATH", str(override))

    assert price_kb_paths.official_kb_path() == override.resolve()
