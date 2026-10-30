"""Build orders: import from aoe4guides.com, follow during a match.

A build is aoe4guides' "overlay" format, imported from a build's link
(GET https://aoe4guides.com/api/builds/<id>?overlay=true) or pasted as JSON,
and kept as-is in the user's data folder (builds/<id>.json). Each step has an
age, a villager count, villagers per resource (food, wood, gold, stone,
builder; -1 = not given) and notes whose icons are `@path.webp@` tokens: the
paths of aoe4guides' own pictures, downloaded once at import and stored as
PNG (builds/icons/), so a match never touches the network.

During a match a step is reached once the villagers seen reach its villager
count and the age is reached (see BuildTracker); buildings cannot be seen, so
they only appear in the notes.
"""

from __future__ import annotations

import io
import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog
from .paths import data_dir
from .state import RESOURCES, GameState

SITE = "https://aoe4guides.com"
API = SITE + "/api/builds/{id}?overlay=true"
PICTURES = SITE + "/assets/pictures/{path}"
TOKEN = re.compile(r"@([\w\-./]+?\.(?:webp|png))@")
BUILD_ID = re.compile(r"^[A-Za-z0-9]{12,40}$")
SLOTS = RESOURCES + ("builder",)   # villager places in a step, in aoe4guides' order of resources
# Villager training time at the town center comes from the catalog (20 s for
# most civilizations, 19 s for the French); slower ones keep 20 s, since it
# only bounds the builders estimate from above.
VILLAGER_DEFAULT_S = 20
LATE_START_S = 20   # a first reading after this game time joined the match late
RALLY = "rally"     # aoe4guides' rally point picture (resource/rally.webp)
MAX_GAP_S = 6       # longest gap between readings counted as production (a menu or alt-tab is not)
TIMEOUT_S = 15


def builds_dir() -> Path:
    d = data_dir() / "builds"
    d.mkdir(exist_ok=True)
    return d


def icons_dir() -> Path:
    return builds_dir() / "icons"


# --- format -------------------------------------------------------------------

def _clock(text) -> int | None:
    """"4:20" -> 260; anything else -> None."""
    m = re.fullmatch(r"\s*(\d+):(\d{1,2})\s*", str(text or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _count(v) -> int | None:
    """A villager count; -1 (or anything not a number) means not given."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


@dataclass(frozen=True)
class BuildStep:
    age: int
    villagers: int | None           # villager_count
    time: int | None                # game seconds, as planned by the author
    targets: dict[str, int | None]  # food, wood, gold, stone, builder
    notes: tuple[str, ...]


@dataclass
class Build:
    id: str
    name: str
    civ: str
    author: str
    source: str
    steps: list[BuildStep]
    raw: dict = field(repr=False, default_factory=dict)

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "civ": self.civ, "author": self.author,
                "source": self.source, "steps": len(self.steps)}


def parse(data: dict, build_id: str | None = None) -> Build:
    """aoe4guides' overlay format -> Build. Raises ValueError when it is not one."""
    if not isinstance(data, dict) or not isinstance(data.get("build_order"), list) or not data["build_order"]:
        raise ValueError("this is not an aoe4guides build order (no build_order steps)")
    steps = []
    for s in data["build_order"]:
        if not isinstance(s, dict):
            raise ValueError("a build order step is not an object")
        res = s.get("resources") or {}
        age = s.get("age")
        steps.append(BuildStep(
            age=age if isinstance(age, int) and 1 <= age <= 4 else (steps[-1].age if steps else 1),
            villagers=_count(s.get("villager_count")),
            time=_clock(s.get("time")),
            targets={k: _count(res.get(k)) for k in SLOTS},
            notes=tuple(n.strip() for n in s.get("notes") or [] if isinstance(n, str) and n.strip()),
        ))
    source = str(data.get("source") or "")
    return Build(id=build_id or id_from_url(source) or _slug(data.get("name", "build")),
                 name=str(data.get("name") or "Untitled build"), civ=str(data.get("civilization") or ""),
                 author=str(data.get("author") or ""), source=source, steps=steps, raw=data)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "build"


def id_from_url(text: str) -> str | None:
    """The build id in an aoe4guides link (…/builds/<id>), or a bare id."""
    text = (text or "").strip()
    m = re.search(r"aoe4guides\.com/(?:api/)?builds/([A-Za-z0-9]+)", text)
    if m:
        return m.group(1)
    return text if BUILD_ID.match(text) else None


def tokens(note: str) -> list[tuple[str, str]]:
    """A note split into ("text", words) and ("icon", picture path) pieces."""
    out, pos = [], 0
    for m in TOKEN.finditer(note):
        if m.start() > pos:
            out.append(("text", note[pos:m.start()]))
        out.append(("icon", m.group(1)))
        pos = m.end()
    if pos < len(note):
        out.append(("text", note[pos:]))
    return out


def icon_paths(build: Build) -> set[str]:
    return {p for s in build.steps for n in s.notes for kind, p in tokens(n) if kind == "icon"}


def icon_file(path: str) -> Path:
    """Where a picture token's icon is stored (always PNG)."""
    return icons_dir() / Path(path).with_suffix(".png")


# --- import and storage -----------------------------------------------------------

def _get(url: str) -> bytes:
    from . import __version__

    req = urllib.request.Request(url, headers={"User-Agent": f"Reeve/{__version__} (+https://github.com/KndHvH/reeve)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return r.read()


def fetch(build_id: str) -> dict:
    return json.loads(_get(API.format(id=build_id)))


def download_icons(build: Build, get=_get) -> list[str]:
    """Downloads the build's icons not stored yet; returns the ones that failed
    (their notes then show the plain name instead)."""
    from PIL import Image

    failed = []
    for path in sorted(icon_paths(build)):
        out = icon_file(path)
        if out.exists():
            continue
        try:
            im = Image.open(io.BytesIO(get(PICTURES.format(path=path)))).convert("RGBA")
        except Exception:
            failed.append(path)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out)
    return failed


def import_build(text: str, get=_get) -> Build:
    """A link to a build on aoe4guides.com (or its id), or the build's JSON
    as the site exports it. Saves it with its icons and returns it."""
    text = (text or "").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ValueError(f"the JSON could not be read ({e.msg}, line {e.lineno})") from None
        build = parse(data)
    else:
        build_id = id_from_url(text)
        if not build_id:
            raise ValueError("paste a link to a build on aoe4guides.com, or the build's JSON")
        try:
            data = json.loads(get(API.format(id=build_id)))
        except Exception as e:
            raise ValueError(f"aoe4guides.com did not return the build ({e})") from None
        build = parse(data, build_id)
    (builds_dir() / f"{build.id}.json").write_text(json.dumps(build.raw, indent=1, ensure_ascii=False), encoding="utf-8")
    download_icons(build, get)
    return build


def refresh(get=_get) -> list[Build]:
    """Imports again every stored build that came from aoe4guides.com and
    returns those whose author changed them (run when Reeve starts). A build
    the site no longer serves, or no network, leaves the stored one as it is."""
    changed = []
    for b in stored():
        build_id = id_from_url(b.source)
        if not build_id:
            continue
        try:
            data = json.loads(get(API.format(id=build_id)))
            new = parse(data, b.id)
        except Exception:
            continue
        if new.raw != b.raw:
            (builds_dir() / f"{b.id}.json").write_text(json.dumps(new.raw, indent=1, ensure_ascii=False), encoding="utf-8")
            download_icons(new, get)
            changed.append(new)
    return changed


def load(build_id: str | None) -> Build | None:
    if not build_id:
        return None
    p = builds_dir() / f"{build_id}.json"
    try:
        return parse(json.loads(p.read_text(encoding="utf-8")), build_id)
    except (OSError, ValueError):
        return None


def stored() -> list[Build]:
    out = []
    for p in sorted(builds_dir().glob("*.json")):
        b = load(p.stem)
        if b is not None:
            out.append(b)
    return sorted(out, key=lambda b: b.name.lower())


def delete(build_id: str) -> bool:
    p = builds_dir() / f"{build_id}.json"
    if p.parent != builds_dir() or not p.exists():
        return False
    p.unlink()
    return True


# --- following a build during a match ---------------------------------------------

def villagers_seen(s: GameState) -> int | None:
    """Villagers the panel accounts for: on each resource, idle and building
    the landmark. Other builders (houses, mines) are not shown anywhere."""
    if s.idle is None or any(s.villagers.get(r) is None for r in RESOURCES):
        return None
    return sum(s.villagers[r] for r in RESOURCES) + s.idle + (s.ageup_builders or 0)


class BuildTracker:
    """Which step the player is on. A step is reached when the most villagers
    counted so far (the same count read twice in a row) reach its villager
    count and its age is reached (a step
    without a villager count waits for its time instead). Only moves forward,
    and may skip steps when the player is ahead.

    Villagers building houses or mines are on no resource, so they are
    estimated from the population: what it holds beyond the villagers seen,
    minus the least it ever held (the scout and other units at the start).
    The population also grows with trained units, so the estimate never goes
    beyond the villagers that can exist: those of the first reading plus one
    per training time the town center was seen producing. Without that (no
    production seen yet), only the villagers seen count."""

    def __init__(self, build: Build):
        self.build = build
        self.index = 0
        self.peak = 0
        self.base: int | None = None         # least population seen beyond the villagers (scout...)
        self.start: int | None = None        # villagers at the first reading
        self.producing_s = 0.0               # game seconds the town center was seen producing villagers
        self._clock: int | None = None
        self.builders = 0                    # villagers estimated to be building (not on the panel)
        self._last: int | None = None        # previous count: a count must be read twice to raise the peak
        self.reached_at: int | None = None   # game clock when the current step was reached
        self.clock: int | None = None        # latest game clock
        self.end_after_s = 30                # the last step stays this long, then the build is over
        self.villager_s = min(catalog.villager_s(build.civ, VILLAGER_DEFAULT_S), VILLAGER_DEFAULT_S)

    def _production(self, s: GameState) -> None:
        if s.clock is not None and self._clock is not None and s.producing_villager:
            self.producing_s += min(max(s.clock - self._clock, 0), MAX_GAP_S)
        if s.clock is not None:
            self._clock = s.clock

    def counted(self, s: GameState) -> int | None:
        """Villagers seen plus the builders estimated from the population."""
        self._production(s)
        seen = villagers_seen(s)
        if seen is None:
            return None
        if s.pop is not None and seen > s.pop:
            return None     # more villagers than population: a misread (the landmark builders read 51 for 5)
        if self.start is None:
            # At the start of a match everyone is visible; joined later (the
            # app started mid-match), builders hide: the population less the scout.
            late = s.clock is not None and s.clock > LATE_START_S and s.pop is not None
            self.start = max(seen, s.pop - 1) if late else seen
        if s.pop is None:
            return seen
        hidden = s.pop - seen
        self.base = hidden if self.base is None else min(self.base, hidden)
        # Rounded: production is confirmed over two readings, so each villager is
        # seen a few seconds short.
        can_exist = self.start + round(self.producing_s / self.villager_s)
        self.builders = max(0, min(hidden - self.base, can_exist - seen))
        return seen + self.builders

    def _reached(self, step: BuildStep, s: GameState) -> bool:
        if (s.age or 1) < step.age:
            return False
        if step.villagers is not None:
            return self.peak >= step.villagers
        return step.time is not None and s.clock is not None and s.clock >= step.time

    def update(self, s: GameState) -> bool:
        """Advances with the new state; True when the step changed."""
        seen = self.counted(s)
        if seen is not None and seen == self._last:   # two reads in a row: one misread never moves the build
            self.peak = max(self.peak, seen)
        self._last = seen
        if s.clock is not None:
            self.clock = s.clock
        if self.reached_at is None and s.clock is not None:
            self.reached_at = s.clock
        steps, i = self.build.steps, self.index
        while i + 1 < len(steps) and self._reached(steps[i + 1], s):
            i += 1
        if i == self.index:
            return False
        self.index, self.reached_at = i, s.clock
        return True

    def window(self) -> tuple[BuildStep | None, BuildStep, BuildStep | None]:
        """Previous, current and next step."""
        steps, i = self.build.steps, self.index
        return (steps[i - 1] if i else None, steps[i], steps[i + 1] if i + 1 < len(steps) else None)

    @property
    def finished(self) -> bool:
        """The last step has been up for end_after_s: the panel and the
        build's alerts are done."""
        return (self.index == len(self.build.steps) - 1 and self.clock is not None
                and self.reached_at is not None and self.clock - self.reached_at >= self.end_after_s)

    def rally(self) -> str | None:
        """Where the town center's rally point should be: the picture the
        current step's notes put it on (\"@rally@ on @sheep@\"), or, when a
        step does not say, the last one that did. None before any does."""
        for step in reversed(self.build.steps[:self.index + 1]):
            for note in step.notes:
                icons = [v for kind, v in tokens(note) if kind == "icon"]
                for a, b in zip(icons, icons[1:]):
                    if Path(a).stem == RALLY:
                        return b
        return None


def instructions(targets: dict[str, int | None], actual: dict[str, int | None]) -> list[tuple]:
    """What to do so the villagers match the step: ("move", n, from, to) while
    a resource has more than the step and another less, then ("put", n, to)
    for what is still missing. Having more than the step is never an issue
    on its own (the player is ahead)."""
    short, extra = {}, {}
    for r in RESOURCES:
        t, a = targets.get(r), actual.get(r)
        if t is None or a is None:
            continue
        if a < t:
            short[r] = t - a
        elif a > t:
            extra[r] = a - t
    out = []
    for dst in sorted(short, key=lambda r: (-short[r], RESOURCES.index(r))):
        while short[dst] and extra:
            src = max(extra, key=lambda r: (extra[r], -RESOURCES.index(r)))
            n = min(short[dst], extra[src])
            out.append(("move", n, src, dst))
            short[dst] -= n
            extra[src] -= n
            if not extra[src]:
                del extra[src]
        if short[dst]:
            out.append(("put", short[dst], dst))
    return out


def describe(inst: tuple) -> str:
    if inst[0] == "move":
        _, n, src, dst = inst
        return f"Move {n} villager{'s' if n != 1 else ''} from {src} to {dst}"
    _, n, dst = inst
    return f"Put {n} villager{'s' if n != 1 else ''} on {dst}"
