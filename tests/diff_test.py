"""Differential test: emoji_rs against the original emoji implementation.

    python -I tests/diff_test.py [--n-fuzz N] [--seed S]

Every case is run through the Rust core *directly* (so that a silent fallback to Python cannot make
the test pass vacuously) and through the public wrappers, and compared with the original function.
"""
import argparse
import itertools
import random
import sys

import emoji
import emoji.core as ec
import emoji.unicode_codes as uc

import emoji_rs

ap = argparse.ArgumentParser()
ap.add_argument("--n-fuzz", type=int, default=20000)
ap.add_argument("--seed", type=int, default=1)
args = ap.parse_args()

core = emoji_rs._State.core
assert core is not None, "Rust core is not active (unsupported emoji release?)"
O = emoji_rs._orig
ZWJ, VS15, VS16 = "‍", "︎", "️"
KEYS = list(uc.EMOJI_DATA)
SPECIAL = (
    [ZWJ] * 4 + [VS15, VS16] * 2 + [chr(c) for c in range(0x1F3FB, 0x1F400)]
    + [chr(c) for c in range(0x1F9B0, 0x1F9B4)] + [chr(c) for c in range(0x1F1E6, 0x1F1EE)]
    + [chr(c) for c in (0xE0062, 0xE0067, 0xE007F)] + ["⃣", "#", "*", "0", "9", "©", "®"]
    + ["♀", "♂", "⚕", "✈", "❤", "☺"]
)
TEXT = ["a", " ", ",", ".", "\n", "Z", "é", "漢", "ж", ":", "_", "\x00", "\U00010000", "​"]
LANGS = ["en", "alias"] + list(uc.LANGUAGES)

# parameter grids -------------------------------------------------------------------------------
DELIMS = [(":", ":"), ("__", "__"), ("{", "}"), ("", ""), ("é", "😀")]
VERSIONS = [None, 0, 0.6, 1, 2.0, 5, 12.1, 13.1, 15.1, 16, 100, -1, -0.5]
HANDLE = [None, "", "?", "[v]"]
REPLACE = ["", "X", "🙂", ":x:"]
RVERS = [-1, -2, -1.0, 0, 0.6, 3, 12.1, 15.1, 100]

stats = {"cases": 0, "fast": 0, "bail": 0, "emoji_hits": 0}
failures = []


def check(what, text, got, want):
    stats["cases"] += 1
    if got != want or type(got) is not type(want):
        failures.append((what, text, got, want))
        if len(failures) <= 10:
            print("MISMATCH", what, repr(text), "\n  rust:", repr(got), "\n  orig:", repr(want))


def run_core(what, fn, *a):
    r = fn(*a)
    if r is None:
        stats["bail"] += 1
    else:
        stats["fast"] += 1
    return r


def one(text, rng, deep):
    for lang in (LANGS if deep else [rng.choice(LANGS)]):
        for d in (DELIMS if deep else [rng.choice(DELIMS)]):
            for ver in (VERSIONS if deep else [rng.choice(VERSIONS)]):
                for hv in (HANDLE if deep else [rng.choice(HANDLE)]):
                    for kz in ((True, False) if deep else (rng.random() < 0.5,)):
                        ec.config.demojize_keep_zwj = kz
                        want = O["demojize"](text, d, lang, ver, hv)
                        use_alias = lang == "alias"
                        l2 = "en" if use_alias else lang
                        uc.load_from_json(l2)
                        if not core.has_language(l2):
                            emoji_rs._lang(core, l2)
                        got = run_core("demojize", core.demojize, text, d[0], d[1], l2, use_alias, ver, hv, kz)
                        check(f"demojize{(d, lang, ver, hv, kz)}", text, got, want)
                        got = emoji_rs.demojize(text, d, lang, ver, hv)
                        check("demojize(wrapper)", text, got, want)
    ec.config.demojize_keep_zwj = True
    for kz in (True, False):
        ec.config.replace_emoji_keep_zwj = kz
        for rep in (REPLACE if deep else [rng.choice(REPLACE)]):
            for ver in (RVERS if deep else [rng.choice(RVERS)]):
                try:
                    want = O["replace_emoji"](text, rep, ver)
                except AssertionError:
                    want = AssertionError
                got = core.replace_emoji(text, rep, float(ver), kz)
                if want is AssertionError:
                    stats["cases"] += 1
                    assert got is None, ("expected a bail-out", text, rep, ver)
                    stats["bail"] += 1
                    try:
                        emoji_rs.replace_emoji(text, rep, ver)
                        failures.append(("replace_emoji should raise", text, rep, ver))
                    except AssertionError:
                        pass
                else:
                    stats["fast"] += got is not None
                    stats["bail"] += got is None
                    check(f"replace_emoji{(rep, ver, kz)}", text, got, want)
                    check("replace_emoji(wrapper)", text, emoji_rs.replace_emoji(text, rep, ver), want)
    ec.config.replace_emoji_keep_zwj = False
    want = O["emoji_list"](text)
    check("emoji_list", text, run_core("emoji_list", core.emoji_list, text), want)
    check("emoji_list(wrapper)", text, emoji_rs.emoji_list(text), want)
    check("distinct_emoji_list", text, emoji_rs.distinct_emoji_list(text), O["distinct_emoji_list"](text))
    check("emoji_count", text, emoji_rs.emoji_count(text), O["emoji_count"](text))
    check("emoji_count(unique)", text, emoji_rs.emoji_count(text, True), O["emoji_count"](text, True))
    check("purely_emoji", text, run_core("purely_emoji", core.purely_emoji, text), O["purely_emoji"](text))
    check("purely_emoji(wrapper)", text, emoji_rs.purely_emoji(text), O["purely_emoji"](text))
    stats["emoji_hits"] += len(want)


rng = random.Random(args.seed)

# 1. every emoji: alone, in text, with VS stripped / added, doubled, ZWJ-joined -----------------------
for k in KEYS:
    stripped = k.replace(VS16, "").replace(VS15, "")
    for t in (k, "x" + k + "y", stripped, k + VS16, k + VS15, k + k, k + ZWJ + k, ZWJ + k, k + ZWJ,
              stripped + ZWJ + "a", "a" + ZWJ + k):
        one(t, rng, deep=False)

# 2. all pairs/triples from a sample, joined with and without ZWJ ----------------------------------------
sample = rng.sample(KEYS, 60) + [k for k in KEYS if k in ("\U0001F468", "\U0001F469", "\U0001F467", "❤️", "\U0001F3FB")]
for a, b in itertools.product(sample, repeat=2):
    for t in (a + b, a + ZWJ + b, a + VS16 + ZWJ + b + VS15):
        one(t, rng, deep=False)
for a, b, c in rng.sample(list(itertools.product(sample, repeat=3)), 800):
    one(a + ZWJ + b + ZWJ + c, rng, deep=False)
    one(a + ZWJ + b + c, rng, deep=False)

# 3. fuzz ------------------------------------------------------------------------------------------------
def piece():
    r = rng.random()
    if r < 0.35:
        return rng.choice(KEYS)
    if r < 0.60:
        return rng.choice(SPECIAL)
    if r < 0.75:
        k = rng.choice(KEYS)
        return k[: rng.randint(1, len(k))]
    if r < 0.85:
        k = rng.choice(KEYS)
        i = rng.randrange(len(k))
        return k[:i] + k[i + 1:]
    return rng.choice(TEXT)


for n in range(args.n_fuzz):
    t = "".join(piece() for _ in range(rng.randint(0, 12)))
    one(t, rng, deep=(n % 500 == 0))

# 4. special inputs: long text, the wrapper's own fallbacks ---------------------------------------------
big = ("Hello 👍 world 👨‍👩‍👧‍👦 " * 500)
one(big, rng, deep=False)
one("", rng, deep=True)
for bad in ("\ud800", "a\udfffb😀"):
    for fn, a in (("demojize", ()), ("replace_emoji", ()), ("emoji_list", ()), ("distinct_emoji_list", ()),
                  ("emoji_count", ()), ("purely_emoji", ())):
        try:
            want = O[fn](bad, *a)
        except Exception as e:  # noqa: BLE001
            want = e
        got = getattr(emoji_rs, fn)(bad, *a)
        stats["cases"] += 1
        if isinstance(want, Exception):
            failures.append((fn, bad, got, want))
        elif got != want:
            failures.append((fn, bad, got, want))
# callables / odd argument types go to the original
cases = [
    lambda f: f("a 😀 b", replace=lambda e, d: d["en"]),
    lambda f: f("a 😀 b", replace=lambda e, d: "<%s>" % e, version=1),
]
for c in cases:
    stats["cases"] += 1
    if c(emoji_rs.replace_emoji) != c(O["replace_emoji"]):
        failures.append(("callable replace", None, None, None))
for hv in (lambda e, d: "[" + e + "]", 5):
    for fn in ("demojize",):
        stats["cases"] += 1
        try:
            w = O[fn]("a 😀 b 🆕", version=0.7, handle_version=hv)
        except Exception as e:  # noqa: BLE001
            w = type(e)
        try:
            g = getattr(emoji_rs, fn)("a 😀 b 🆕", version=0.7, handle_version=hv)
        except Exception as e:  # noqa: BLE001
            g = type(e)
        if g != w:
            failures.append(("handle_version", hv, g, w))
for bad in ("xx", "", "zz"):
    stats["cases"] += 1
    try:
        O["demojize"]("😀", language=bad)
        w = None
    except Exception as e:  # noqa: BLE001
        w = type(e)
    try:
        emoji_rs.demojize("😀", language=bad)
        g = None
    except Exception as e:  # noqa: BLE001
        g = type(e)
    if g != w:
        failures.append(("bad language", bad, g, w))
for notstr in (b"abc", 5, None, ["😀"]):
    for fn in ("demojize", "replace_emoji", "emoji_list", "emoji_count", "purely_emoji"):
        stats["cases"] += 1
        try:
            w = repr(O[fn](notstr))
        except Exception as e:  # noqa: BLE001
            w = type(e)
        try:
            g = repr(getattr(emoji_rs, fn)(notstr))
        except Exception as e:  # noqa: BLE001
            g = type(e)
        if g != w:
            failures.append((fn, notstr, g, w))

print(f"cases={stats['cases']} rust-served={stats['fast']} bailouts={stats['bail']} "
      f"emoji-matches-seen={stats['emoji_hits']} failures={len(failures)}")
assert stats["fast"] > 0.9 * (stats["fast"] + stats["bail"]), "fast path barely exercised"
sys.exit(1 if failures else 0)
