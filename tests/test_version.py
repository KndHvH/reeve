from reeve import version


def _describe(monkeypatch, out, since_tag=""):
    """`out`: what git describe prints; `since_tag`: the ancestry-path count
    (empty = git gave nothing, describe's count stays)."""
    monkeypatch.setattr(version, "_git", lambda *a: out if a[0] == "describe" else since_tag)
    monkeypatch.setattr(version, "__version__", "0.2.2")


def test_release_commit_shows_the_plain_number(monkeypatch):
    _describe(monkeypatch, "v0.2.2-0-gb0c37b9")
    assert version.from_git() == "0.2.2"


def test_work_after_the_last_release_is_marked(monkeypatch):
    _describe(monkeypatch, "v0.2.1-7-gb0c37b9")
    assert version.from_git() == "0.2.2-dev.7+b0c37b9"
    _describe(monkeypatch, "v0.2.1-7-gb0c37b9-dirty")
    assert version.from_git() == "0.2.2-dev.7+b0c37b9.dirty"


def test_a_tagged_commit_with_local_changes_is_not_the_release(monkeypatch):
    _describe(monkeypatch, "v0.2.2-0-gb0c37b9-dirty")
    assert version.from_git() == "0.2.2-dev.0+b0c37b9.dirty"


def test_without_git_it_still_says_dev(monkeypatch):
    _describe(monkeypatch, "")
    assert version.from_git() == "0.2.2-dev"


def test_squash_merged_commits_are_not_counted_again(monkeypatch):
    # describe counts the 21 commits outside the tag's history; only 6 came after the release
    _describe(monkeypatch, "v0.2.1-21-gb0c37b9", since_tag="6")
    assert version.from_git() == "0.2.2-dev.6+b0c37b9"
