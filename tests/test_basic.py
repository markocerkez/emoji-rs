import warnings

import pytest

import emoji
import emoji.core as ec
import emoji.unicode_codes as uc

import emoji_rs as R

O = R._orig
FAMILY = "\U0001F468‍\U0001F469‍\U0001F467"  # RGI ZWJ sequence
NON_RGI = "\U0001F642‍\U0001F600"  # two emoji joined by ZWJ, not in EMOJI_DATA
TEXT = f"Hi 👍 {FAMILY} {NON_RGI} 🇨🇭 ❤️ ❤︎ #️⃣ x"


@pytest.fixture(autouse=True)
def _restore_config():
    d, r = ec.config.demojize_keep_zwj, ec.config.replace_emoji_keep_zwj
    yield
    ec.config.demojize_keep_zwj, ec.config.replace_emoji_keep_zwj = d, r
    R.unpatch()


def test_core_is_active():
    assert R._State.core is not None


@pytest.mark.parametrize("keep", [True, False])
def test_demojize_matches_original(keep):
    ec.config.demojize_keep_zwj = keep
    for args in [(), ((":", ":"),), (("{", "}"),), ((":", ":"), "de"), ((":", ":"), "alias"),
                 ((":", ":"), "en", 1.0, "?")]:
        assert R.demojize(TEXT, *args) == O["demojize"](TEXT, *args)


@pytest.mark.parametrize("keep", [True, False])
def test_replace_emoji_matches_original(keep):
    ec.config.replace_emoji_keep_zwj = keep
    for args in [(), ("X",), ("X", 5), ("", 0.6)]:
        try:
            want = O["replace_emoji"](TEXT, *args)
        except AssertionError:  # keep_zwj + version + a joined non-RGI group
            with pytest.raises(AssertionError):
                R.replace_emoji(TEXT, *args)
        else:
            assert R.replace_emoji(TEXT, *args) == want


def test_non_rgi_zwj_sequences():
    ec.config.demojize_keep_zwj = True
    assert R.demojize(NON_RGI) == O["demojize"](NON_RGI)
    ec.config.demojize_keep_zwj = False
    assert R.demojize(NON_RGI) == O["demojize"](NON_RGI)
    ec.config.replace_emoji_keep_zwj = True
    assert R.replace_emoji(NON_RGI, "<>") == O["replace_emoji"](NON_RGI, "<>") == "<>"
    ec.config.replace_emoji_keep_zwj = False
    assert R.replace_emoji(NON_RGI, "<>") == "<><>"


def test_keep_zwj_with_version_raises_like_the_original():
    ec.config.replace_emoji_keep_zwj = True
    with pytest.raises(AssertionError):
        O["replace_emoji"](NON_RGI, "X", 5)
    with pytest.raises(AssertionError):
        R.replace_emoji(NON_RGI, "X", 5)


def test_component_rewinding():
    # skin-tone components glued to ZWJ sequences exercise the rewind branch of the tokenizer
    for s in ["\U0001F468\U0001F3FB‍\U0001F469", "\U0001F3FB‍\U0001F469", "a‍\U0001F3FB"]:
        assert R.demojize(s) == O["demojize"](s)
        assert R.emoji_list(s) == O["emoji_list"](s)


def test_emoji_list_shape():
    out = R.emoji_list("Hi, I am fine. 😁")
    assert out == [{"match_start": 15, "match_end": 16, "emoji": "😁"}]
    assert list(out[0]) == ["match_start", "match_end", "emoji"]


def test_distinct_and_count():
    s = "😁😁👍a👍🇨🇭"
    assert R.distinct_emoji_list(s) == O["distinct_emoji_list"](s)
    assert R.emoji_count(s) == 5 and R.emoji_count(s, True) == 3
    assert R.purely_emoji("😁👍") and not R.purely_emoji("a😁") and R.purely_emoji("")


def test_callables_use_the_original():
    assert R.replace_emoji("a😁", lambda e, d: d["en"]) == O["replace_emoji"]("a😁", lambda e, d: d["en"])
    f = lambda e, d: "[" + e + "]"  # noqa: E731
    assert R.demojize("a🆕😁", version=0.7, handle_version=f) == O["demojize"]("a🆕😁", version=0.7, handle_version=f)


def test_unknown_language_raises_like_the_original():
    with pytest.raises(NotImplementedError):
        R.demojize("😁", language="xx")


def test_lone_surrogate_and_non_str_fall_back():
    for bad in ("\ud800", "a\udfff😁"):
        assert R.demojize(bad) == O["demojize"](bad)
    with pytest.raises(TypeError):
        R.demojize(b"abc")


def test_patch_unpatch():
    assert not R.is_patched()
    assert R.patch() and R.is_patched()
    assert emoji.demojize is R.demojize and ec.demojize is R.demojize
    assert emoji.emoji_list is R.emoji_list
    assert emoji.demojize(TEXT) == O["demojize"](TEXT)
    R.unpatch()
    assert not R.is_patched() and emoji.demojize is O["demojize"]


def test_modified_emoji_data_is_detected():
    key = "\U0001F9FF\U0001F9FF\U0001F9FF"
    uc.EMOJI_DATA[key] = {"en": ":triple:", "status": 2, "E": 1}
    try:
        # the table is stale -> the wrappers use the original implementation
        assert R._live() is None
        assert R.demojize("a" + key) == O["demojize"]("a" + key)
        R.refresh()
        assert R._live() is not None
    finally:
        del uc.EMOJI_DATA[key]
        R.refresh()
    assert R._live() is not None


def test_unverified_emoji_release_is_not_patched(monkeypatch):
    monkeypatch.setattr(R, "_supported", lambda: False)
    saved = R._State.core
    R._State.core = None
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert R.patch() is False
        assert w and "not patching" in str(w[0].message)
        assert not R.is_patched()
    finally:
        R._State.core = saved
