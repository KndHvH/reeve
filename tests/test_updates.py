import hashlib

import pytest

from reeve import updates
from reeve.checks import load_state

API = {"tag_name": "v0.3.0", "html_url": "https://github.com/KndHvH/reeve/releases/tag/v0.3.0",
       "assets": [{"name": "Reeve-0.3.0-setup.exe", "size": 3, "digest": "sha256:" + "ab" * 32,
                   "browser_download_url": "https://github.com/x/Reeve-0.3.0-setup.exe"}]}


def test_versions_compare_as_numbers():
    assert updates.parse_version("v0.10.0") > updates.parse_version("0.9.9")
    assert updates.parse_version("garbage") == (0,)
    assert updates.parse_version("0.2.2.1") > updates.parse_version("0.2.2") > updates.parse_version("0.2.1.99")
    rel = updates._from_api(API)
    assert updates.newer(rel, "0.2.1") and not updates.newer(rel, "0.3.0") and not updates.newer(None)


def test_release_from_the_api_keeps_installer_size_and_checksum():
    rel = updates._from_api(API)
    assert (rel.version, rel.size, rel.sha256) == ("0.3.0", 3, "ab" * 32)
    assert updates._from_api(API | {"assets": []}).installer is None


def test_github_is_asked_at_most_once_a_day():
    calls = []
    fetch = lambda: calls.append(1) or updates._from_api(API)
    assert updates.check(fetch=fetch, now=1000).version == "0.3.0"
    assert updates.check(fetch=fetch, now=1000 + 3600).version == "0.3.0"     # from the last check
    assert len(calls) == 1
    updates.check(fetch=fetch, now=1000 + 25 * 3600)
    updates.check(force=True, fetch=fetch, now=1000 + 25 * 3600 + 1)        # "Check now" in the hub
    assert len(calls) == 3
    assert load_state()["update"]["latest"]["version"] == "0.3.0"


def test_offline_keeps_the_last_answer():
    updates.check(fetch=lambda: updates._from_api(API), now=0)
    def offline():
        raise OSError("no network")
    assert updates.check(fetch=offline, now=10 * 24 * 3600).version == "0.3.0"


def test_download_is_verified(tmp_path):
    src = tmp_path / "setup.exe"
    src.write_bytes(b"abc")
    good = updates.Release("9.9.9", "page", src.as_uri(), 3, hashlib.sha256(b"abc").hexdigest())
    assert updates.download(good).read_bytes() == b"abc"
    with pytest.raises(ValueError, match="checksum"):
        updates.download(updates.Release("9.9.8", "page", src.as_uri(), 3, "00" * 32))
    with pytest.raises(ValueError, match="incomplete"):
        updates.download(updates.Release("9.9.7", "page", src.as_uri(), 4, None))


@pytest.mark.skipif(not hasattr(__import__("subprocess"), "CREATE_NO_WINDOW"), reason="Windows only")
def test_install_command_starts_the_installer_through_cmd(tmp_path):
    # A stand-in installer in a folder with spaces, run through the real cmd.exe
    # line: it must receive the path intact and the silent arguments.
    import subprocess
    import time

    folder = tmp_path / "Temp dir"
    folder.mkdir()
    out = folder / "ran.txt"
    fake = folder / "Reeve-0.3.0-setup.cmd"
    fake.write_text(f'@echo %* > "{out}"\r\n', encoding="ascii")
    line = updates.install_command(fake)
    assert '\\"' not in line
    subprocess.run(line, creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=30)
    for _ in range(50):
        if out.exists() and out.read_text().strip():
            break
        time.sleep(0.1)
    assert "/SILENT" in out.read_text() and "/RELAUNCH=1" in out.read_text()
