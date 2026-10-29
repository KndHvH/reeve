import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path_factory, monkeypatch):
    """Tests never touch the user's real data folder (%APPDATA%\aoe4ov); it gets
    its own temp folder, apart from the test's tmp_path."""
    monkeypatch.setenv("AOE4OV_HOME", str(tmp_path_factory.mktemp("aoe4ov_home")))
