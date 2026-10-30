"""Release pipelines: the recurring git and GitHub steps, ready to run.

    uv run python scripts/release.py status            # branches, version, CI, open release PR
    uv run python scripts/release.py prepare 0.2.3     # on unstable: bump version, notes file
    uv run python scripts/release.py pr                # PR unstable -> main, waits for CI
    uv run python scripts/release.py publish           # after the PR is merged: release from main
    uv run python scripts/release.py test-installer 0.2.2.99   # build numbered below, to try updates

Branch model: day-to-day work goes to `unstable`; `main` only receives it
through a pull request, merged by the maintainer with squash (one commit per
version). After that merge, `publish` builds the release from `main`, tags it,
and realigns `unstable` on `main`: the squash leaves the released commits
outside main's history, so `unstable` is moved onto `main` with any commit
made after the release PR replayed on top, and pushed with
--force-with-lease (the maintainer's choice, so GitHub shows `unstable` with
only the new work after each release). Nothing here merges into main.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "src" / "reeve" / "__init__.py"
PYPROJECT = REPO / "pyproject.toml"
NOTES = REPO / "docs" / "releases"
ATTRIBUTION = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def run(*cmd: str, check: bool = True, capture: bool = True) -> str:
    r = subprocess.run(cmd, cwd=REPO, text=True, encoding="utf-8", errors="replace", capture_output=capture)
    if check and r.returncode:
        sys.exit(f"failed: {' '.join(cmd)}\n{(r.stderr or r.stdout or '').strip()}")
    return (r.stdout or "").strip()


def git(*args: str, **kw) -> str:
    return run("git", *args, **kw)


def git_ok(*args: str) -> bool:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True).returncode == 0


def version() -> str:
    return re.search(r'__version__ = "([^"]+)"', INIT.read_text(encoding="utf-8")).group(1)


def require_clean(branch: str) -> None:
    if git("rev-parse", "--abbrev-ref", "HEAD") != branch:
        sys.exit(f"switch to {branch} first")
    if git("status", "--porcelain"):
        sys.exit("the working tree has uncommitted changes: commit or stash them first")


def release_pr() -> dict | None:
    out = run("gh", "pr", "list", "--base", "main", "--head", "unstable", "--state", "open",
              "--json", "number,url,title")
    prs = json.loads(out or "[]")
    return prs[0] if prs else None


def unreleased(fmt: str | None = None, branch: str = "origin/unstable") -> str:
    """The work on unstable that is not in main yet. A squash merge puts a new
    commit on main and leaves the original ones outside its history, so
    `tag..unstable` would count every released commit again; the ancestry path
    from main only reaches what came after it (also for older releases, which
    merged main back into unstable instead of realigning it)."""
    args = ["--no-merges", "--ancestry-path", f"origin/main..{branch}"]
    return git("log", f"--format={fmt}", *args) if fmt else git("rev-list", "--count", *args)


def cmd_status(_args) -> None:
    git("fetch", "-q")
    v = version()
    last = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "origin/main", check=False)
    ahead = unreleased()
    print(f"version in code:   {v}")
    print(f"last release tag:  {last or 'none'}")
    print(f"branch:            {git('rev-parse', '--abbrev-ref', 'HEAD')}"
          + (" (uncommitted changes)" if git("status", "--porcelain") else ""))
    print(f"unstable:          {ahead} commits since {last}")
    print(f"unstable vs main:  {'same files' if not git('diff', 'origin/main', 'origin/unstable') else 'differs'}")
    ci = run("gh", "run", "list", "--branch", "unstable", "--limit", "1", "--json", "conclusion,status,displayTitle")
    for r in json.loads(ci or "[]"):
        print(f"CI on unstable:    {r['conclusion'] or r['status']} ({r['displayTitle']})")
    pr = release_pr()
    print(f"release PR:        {pr['url'] if pr else 'none open'}")
    if last == f"v{v}":
        print(f"\nv{v} is released: run `prepare <next version>` before the next release")


def cmd_prepare(args) -> None:
    require_clean("unstable")
    new = args.version
    # X.Y.Z, or X.Y.Z.N for a fix to an existing release (numbers only: they
    # compare as numbers in update checks and Windows file versions).
    if not re.fullmatch(r"\d+\.\d+\.\d+(\.\d+)?", new):
        sys.exit("version must look like 0.2.3 (or 0.2.2.1 for a fix)")
    INIT.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{new}"', INIT.read_text(encoding="utf-8")),
                    encoding="utf-8")
    PYPROJECT.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{new}"',
                                PYPROJECT.read_text(encoding="utf-8")), encoding="utf-8")
    run("uv", "lock")
    notes = NOTES / f"v{new}.md"
    if not notes.exists():
        last = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "origin/main", check=False)
        log = unreleased("- %s", "HEAD")
        notes.write_text(f"<!-- Release notes for players: what is new, improved and fixed. Commits since {last}:\n"
                         f"{log}\n-->\n\n## New\n\n## Improved\n\n## Fixed\n\n## Install\n"
                         f"Download `Reeve-{new}-setup.exe` below and run it, or use Update now in the hub.\n",
                         encoding="utf-8")
    git("add", str(INIT), str(PYPROJECT), str(REPO / "uv.lock"), str(notes))
    git("commit", "-q", "-m", f"Version {new}\n\n{ATTRIBUTION}")
    git("push", "-q")
    print(f"version {new} committed on unstable; write the notes in {notes.relative_to(REPO)}, check the README "
          "screenshots (docs/screenshots) against the current UI and retake those that changed, commit, then run `pr`")


def cmd_pr(_args) -> None:
    require_clean("unstable")
    v = version()
    notes = NOTES / f"v{v}.md"
    if not notes.exists():
        sys.exit(f"missing release notes: {notes.relative_to(REPO)} (run `prepare {v}`)")
    git("push", "-q")
    pr = release_pr()
    if pr is None:
        body = re.sub(r"<!--.*?-->\s*", "", notes.read_text(encoding="utf-8"), flags=re.S).strip()
        body += "\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"
        url = run("gh", "pr", "create", "--base", "main", "--head", "unstable", "--title", f"Reeve {v}", "--body", body)
    else:
        url = pr["url"]
    print(f"release PR: {url}\nwaiting for CI...")
    run("gh", "pr", "checks", url, "--watch", "--interval", "20", check=False, capture=False)
    print(f"\nWhen CI is green, the maintainer merges it (squash): {url}\nThen run `publish`.")


def cmd_publish(_args) -> None:
    git("fetch", "-q")
    if git("status", "--porcelain"):
        sys.exit("the working tree has uncommitted changes: commit or stash them first")
    git("checkout", "-q", "main")
    git("pull", "-q", "--ff-only")
    v = version()
    if git("tag", "--list", f"v{v}"):
        sys.exit(f"v{v} is already released")
    if git("diff", "main", "origin/unstable"):
        print("note: unstable has changes that are not in main; only main is released")
    print(f"building and publishing v{v} from main ({git('rev-parse', '--short', 'HEAD')})...")
    run(sys.executable, "scripts/build.py", "--release", capture=False)
    realign_unstable(v)


def realign_unstable(v: str) -> None:
    """Moves unstable onto main after the squash: what the release PR held is
    in main as one commit; anything committed after the PR is replayed on top.
    The old unstable stays in a local backup branch."""
    git("checkout", "-q", "unstable")
    git("pull", "-q", "--ff-only")
    old = git("rev-parse", "HEAD")
    merged = json.loads(run("gh", "pr", "list", "--base", "main", "--head", "unstable", "--state", "merged",
                            "--limit", "1", "--json", "headRefOid") or "[]")
    released = merged[0]["headRefOid"] if merged else None
    git("branch", "-f", "backup/unstable-before-realign", old)
    if released and git_ok("merge-base", "--is-ancestor", released, old):
        if not git_ok("rebase", "--onto", "main", released, "unstable"):
            git_ok("rebase", "--abort")
            sys.exit("unstable could not be replayed onto main and was left as it was; realign it by hand")
    elif git("diff", "main", "unstable"):
        sys.exit("unstable has changes not in main and the merged release PR was not found; realign it by hand")
    else:
        git("reset", "-q", "--hard", "main")
    git("push", "-q", f"--force-with-lease=unstable:{old}", "origin", "unstable")
    after = git("rev-list", "--count", "main..unstable")
    print(f"released v{v}; unstable realigned on main ({after} commit(s) of new work)")


def cmd_test_installer(args) -> None:
    n = args.version
    if not re.fullmatch(r"\d+(\.\d+){2,3}", n):
        sys.exit("give a plain number below the latest release, e.g. 0.2.2.99")
    run(sys.executable, "scripts/build.py", "--as-version", n, capture=False)
    print(f"\ninstall dist/Reeve-{n}-test-setup.exe, open the hub: it should offer the latest release")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="branches, version, CI and the open release PR")
    p = sub.add_parser("prepare", help="on unstable: set the next version and create its notes")
    p.add_argument("version")
    sub.add_parser("pr", help="open (or find) the release PR unstable -> main and wait for CI")
    sub.add_parser("publish", help="after the merge: build and publish the release, realign unstable")
    t = sub.add_parser("test-installer", help="installer numbered below the latest release, to test updating")
    t.add_argument("version")
    args = ap.parse_args()
    {"status": cmd_status, "prepare": cmd_prepare, "pr": cmd_pr, "publish": cmd_publish,
     "test-installer": cmd_test_installer}[args.cmd](args)


if __name__ == "__main__":
    main()
