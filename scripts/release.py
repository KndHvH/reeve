"""Release pipelines: the recurring git and GitHub steps, ready to run.

    uv run python scripts/release.py status            # branches, version, CI, open release PR
    uv run python scripts/release.py prepare 0.2.3     # on unstable: bump version, notes file
    uv run python scripts/release.py pr                # PR unstable -> main, waits for CI
    uv run python scripts/release.py publish           # after the PR is merged: release from main
    uv run python scripts/release.py test-installer 0.2.2.99   # build numbered below, to try updates

Branch model: day-to-day work goes to `unstable`; `main` only receives it
through a pull request, merged by the maintainer with squash (one commit per
version). After that merge, `publish` builds the release from `main`, tags it,
and merges `main` back into `unstable` (a squash leaves the two histories
apart; the merge reconnects them without changing any file). Nothing here
merges into main, force-pushes or rewrites history.
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
    r = subprocess.run(cmd, cwd=REPO, text=True, capture_output=capture)
    if check and r.returncode:
        sys.exit(f"failed: {' '.join(cmd)}\n{(r.stderr or r.stdout or '').strip()}")
    return (r.stdout or "").strip()


def git(*args: str, **kw) -> str:
    return run("git", *args, **kw)


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


def cmd_status(_args) -> None:
    git("fetch", "-q")
    v = version()
    last = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "origin/main", check=False)
    ahead = git("rev-list", "--count", f"{last}..origin/unstable") if last else "?"
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
        log = git("log", "--no-merges", "--format=- %s", f"{last}..HEAD") if last else ""
        notes.write_text(f"<!-- Release notes for players: what is new, improved and fixed. Commits since {last}:\n"
                         f"{log}\n-->\n\n## New\n\n## Improved\n\n## Fixed\n\n## Install\n"
                         f"Download `Reeve-{new}-setup.exe` below and run it, or use Update now in the hub.\n",
                         encoding="utf-8")
    git("add", str(INIT), str(PYPROJECT), str(REPO / "uv.lock"), str(notes))
    git("commit", "-q", "-m", f"Version {new}\n\n{ATTRIBUTION}")
    git("push", "-q")
    print(f"version {new} committed on unstable; write the notes in {notes.relative_to(REPO)}, commit, then run `pr`")


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
    git("checkout", "-q", "unstable")
    git("pull", "-q", "--ff-only")
    if git("rev-list", "--count", "unstable..main") != "0":
        git("merge", "-q", "--no-ff", "main", "-m", f"Merge main (release {v}) back into unstable\n\n{ATTRIBUTION}")
        git("push", "-q")
    print(f"released v{v}; unstable is in step with main")


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
