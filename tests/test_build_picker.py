from reeve.build_picker import elide


def _measure(text):
    return len(text) * 10     # 10 px a character


def test_short_names_stay_whole():
    assert elide("Mali", 100, _measure) == "Mali"


def test_long_names_end_in_an_ellipsis_within_the_width():
    out = elide("English fast castle into longbow timing push", 100, _measure)
    assert out.endswith("…") and _measure(out) <= 100
    assert out == "English f…"


def test_no_space_before_the_ellipsis():
    assert elide("English fast", 90, _measure) == "English…"
