from reeve.income import IncomeTracker
from reeve.state import RESOURCES, GameState


def _state(clock, food, vil_food=5):
    res = {r: 0 for r in RESOURCES} | {"food": food}
    vils = {r: 0 for r in RESOURCES} | {"food": vil_food}
    return GameState(clock=clock, resources=res, villagers=vils)


def test_income_counts_increases_and_ignores_spending():
    t = IncomeTracker(window_s=60)
    food = 0
    inc = None
    for clock in range(0, 62, 2):
        food += 10                      # +10 every 2 s = 300/min
        if clock == 30:
            food -= 50                  # a purchase: must not reduce income
        inc = t.update(_state(clock, food))
    # The purchase lands in the same reading as a drop-off and hides part of
    # it (plus one reading of median-filter lag): the estimate leans low, but
    # the 50 spent is not subtracted (that would give ~250 or less).
    assert 255 <= inc.per_min["food"] <= 300
    assert 51 <= inc.per_villager["food"] <= 60


def test_single_frame_misread_does_not_create_income():
    t = IncomeTracker(window_s=60)
    seq = [1050] * 10 + [105] + [1050] * 10   # one frame lost a digit
    inc = None
    for i, v in enumerate(seq):
        inc = t.update(_state(2 * i, v))
    assert inc.per_min["food"] == 0


def test_no_rate_before_ten_seconds_of_data():
    t = IncomeTracker()
    assert t.update(_state(0, 100)).per_min["food"] is None
    assert t.update(_state(4, 120)).per_min["food"] is None
