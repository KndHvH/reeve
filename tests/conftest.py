import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path_factory, monkeypatch):
    """Tests never touch the user's real data folder (%APPDATA%\reeve); it gets
    its own temp folder, apart from the test's tmp_path."""
    monkeypatch.setenv("REEVE_HOME", str(tmp_path_factory.mktemp("reeve_home")))
