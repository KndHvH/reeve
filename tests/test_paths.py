import json
import os
from pathlib import Path

from aoe4ov import paths


def test_data_dir_follows_env(tmp_path):
    assert paths.data_dir() == Path(os.environ["AOE4OV_HOME"])
    assert paths.sessions_dir().parent == paths.data_dir()


def test_user_overrides_merge_on_top_of_defaults():
    defaults = paths.load_config()
    paths.save_overrides({"sound": {"volume": 0.4}, "tc_idle": {"critical_after_s": 15}})
    cfg = paths.load_config()
    assert cfg["sound"]["volume"] == 0.4
    assert cfg["sound"]["warn"] == defaults["sound"]["warn"]          # untouched keys keep defaults
    assert cfg["tc_idle"]["critical_after_s"] == 15
    assert cfg["housed"] == defaults["housed"]                        # new/other sections come from defaults
    assert json.loads(paths.user_config_path().read_text(encoding="utf-8")) == {
        "sound": {"volume": 0.4}, "tc_idle": {"critical_after_s": 15}}


def test_migrate_moves_sessions(tmp_path):
    from aoe4ov.cli import main

    old = tmp_path / "old_sessions"
    (old / "20260101-000000").mkdir(parents=True)
    (old / "20260101-000000" / "log.jsonl").write_text("{}\n", encoding="utf-8")
    assert main(["migrate", str(old)]) == 0
    assert (paths.sessions_dir() / "20260101-000000" / "log.jsonl").exists()
    assert not (old / "20260101-000000").exists()
