"""Benchmark: original emoji vs emoji_rs.   python -I bench/bench.py"""
import random
import time

import emoji
import emoji.unicode_codes as uc

import emoji_rs

O = emoji_rs._orig
rng = random.Random(7)
KEYS = [k for k, d in uc.EMOJI_DATA.items() if d["status"] == 2]
WORDS = "the quick brown fox jumps over lazy dog hello world great job thanks see you tomorrow lol".split()


def chat(n_chars, density=0.04):
    out, n = [], 0
    while n < n_chars:
        piece = rng.choice(KEYS) if rng.random() < density * 5 else rng.choice(WORDS) + " "
        out.append(piece)
        n += len(piece)
    return "".join(out)[:n_chars]


def best(fn, repeat=3):
    t = []
    for _ in range(repeat):
        s = time.perf_counter()
        fn()
        t.append(time.perf_counter() - s)
    return min(t)


long_text = chat(1_000_000)
short = [chat(100) for _ in range(5000)]
emoji_heavy = "".join(rng.choice(KEYS) for _ in range(20000))
print(f"emoji {emoji.__version__}, long text {len(long_text):,} chars, {len(short)} short strings (100 chars)")
rows = []


def row(name, orig, fast, long=True):
    a, b = best(orig), best(fast)
    rows.append((name, a, b))
    print(f"| {name} | {a*1000:.1f} ms | {b*1000:.2f} ms | {a/b:.0f}x |")


print("| operation | original | Rust | speedup |\n|---|---:|---:|---:|")
for name in ("demojize", "replace_emoji", "emoji_list", "distinct_emoji_list", "emoji_count"):
    o, f = O[name], getattr(emoji_rs, name)
    arg = (lambda: ()) if True else None
    row(f"`{name}` (1 MB text)", lambda: o(long_text), lambda: f(long_text))
    row(f"`{name}` (5000 x 100 chars)", lambda: [o(s) for s in short], lambda: [f(s) for s in short])
pure = "".join(rng.choice(KEYS) for _ in range(200_000))
row("`purely_emoji` (200k emoji, True)", lambda: O["purely_emoji"](pure), lambda: emoji_rs.purely_emoji(pure))
row("`demojize` (20k emoji, no text)", lambda: O["demojize"](emoji_heavy), lambda: emoji_rs.demojize(emoji_heavy))
row("`demojize(language='de')` (1 MB)", lambda: O["demojize"](long_text, language="de"),
    lambda: emoji_rs.demojize(long_text, language="de"))
row("`replace_emoji('X')` 1 MB", lambda: O["replace_emoji"](long_text, "X"), lambda: emoji_rs.replace_emoji(long_text, "X"))
