import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path_factory, monkeypatch):
    """Tests never touch the user's real data folder (%APPDATA%\reeve); it gets
    its own temp folder, apart from the test's tmp_path."""
    monkeypatch.setenv("REEVE_HOME", str(tmp_path_factory.mktemp("reeve_home")))


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    """Tests read English texts whatever the Windows language: "auto" resolves
    to English, and no language is applied yet."""
    from reeve import i18n

    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    monkeypatch.setattr(i18n, "_lang", None)
    monkeypatch.setattr(i18n, "_strings", {})
