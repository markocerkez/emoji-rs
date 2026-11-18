# emoji-rs

Rust-accelerated `demojize`, `replace_emoji`, `emoji_list` and friends for the
[emoji](https://github.com/carpedm20/emoji) package. Output is identical to the original; anything the
Rust core does not handle is passed to the original implementation.

```python
import emoji, emoji_rs
emoji_rs.patch()                 # emoji.demojize / replace_emoji / emoji_list / ... now use Rust
emoji.demojize("Python is fun 👍")
emoji_rs.unpatch()               # restore the original implementation
```

or call `emoji_rs.demojize(...)` etc. directly. Names imported earlier with `from emoji import demojize`
keep pointing at the original; patch first or import from `emoji_rs`.

## Speed

emoji 2.16.0, Python 3.13, 2 cores (`bench/bench.py`). The original builds a `Token` object for every
character of the input, so it runs at about 3 MB/s regardless of how many emoji the text contains:

| operation | original | Rust | speedup |
|---|---:|---:|---:|
| `demojize` (1 MB text) | 365.5 ms | 13.50 ms | 27x |
| `demojize` (5000 x 100 chars) | 189.0 ms | 11.19 ms | 17x |
| `replace_emoji` (1 MB text) | 348.6 ms | 8.42 ms | 41x |
| `replace_emoji` (5000 x 100 chars) | 186.0 ms | 6.77 ms | 27x |
| `emoji_list` (1 MB text) | 327.6 ms | 20.65 ms | 16x |
| `emoji_list` (5000 x 100 chars) | 160.0 ms | 13.92 ms | 11x |
| `distinct_emoji_list` (1 MB text) | 320.7 ms | 14.77 ms | 22x |
| `distinct_emoji_list` (5000 x 100 chars) | 175.9 ms | 11.94 ms | 15x |
| `emoji_count` (1 MB text) | 329.0 ms | 7.85 ms | 42x |
| `emoji_count` (5000 x 100 chars) | 150.4 ms | 5.76 ms | 26x |
| `purely_emoji` (200k emoji, True) | 315.0 ms | 12.15 ms | 26x |
| `demojize` (20k emoji, no text) | 29.5 ms | 1.92 ms | 15x |
| `demojize(language='de')` (1 MB) | 349.5 ms | 12.90 ms | 27x |
| `replace_emoji('X')` 1 MB | 346.5 ms | 7.60 ms | 46x |

Short strings gain less because the call overhead (Python wrapper plus argument conversion, about 1.5 µs)
becomes visible, and `emoji_list` builds one Python dict per match, which stays in Python's hands.

## What is ported

* `emoji.tokenizer.tokenize`, line by line, including its quirks: greedy trie walk without backtracking,
  the `ignore` list for ZWJ characters, rewinding for non-RGI ZWJ sequences and for components,
  variation selectors (`U+FE0E` / `U+FE0F`) being dropped, and `filter_tokens` joining.
* `demojize` (all languages, `delimiters`, `version`, string `handle_version`, `language='alias'`,
  `config.demojize_keep_zwj`), `replace_emoji` (string replacement, `version`,
  `config.replace_emoji_keep_zwj`), `emoji_list`, `distinct_emoji_list`, `emoji_count`, `purely_emoji`.

Not ported, because the gain is small or the result is made of Python objects: `emojize` (already regex based),
`is_emoji` (a dict lookup), `analyze` / `tokenize` (return `EmojiMatch` objects), `version`.

The emoji data is not baked into the wheel: the Rust tables are built from the live `emoji.EMOJI_DATA` when
`emoji_rs` is imported (a few milliseconds) and per-language names when a language is first used. A new emoji
release therefore needs no new emoji-rs release.

## Fallbacks (results stay identical)

Callables for `replace` / `handle_version`, non-`str` arguments, lone surrogates, unknown languages (the
original raises its usual error), `config.*_keep_zwj` combined with `version` for joined non-RGI sequences
(the original raises `AssertionError`), and any case where `EMOJI_DATA` was modified in place after import
(call `emoji_rs.refresh()` to rebuild the tables).

The ported algorithms are identical in emoji 2.13.2 to 2.16.0. For any other release `emoji_rs` hashes the
source of the ported functions (`tools/source_hashes.py`) and keeps the fast path off, with a warning from
`patch()`, unless the digest matches a verified release.

## Testing

* `tests/diff_test.py` runs every case through the Rust core directly (so a silent fallback cannot make the
  test pass vacuously) and through the public wrappers, and compares with the original: all 5244 emoji alone
  and in context (with/without variation selectors, doubled, ZWJ-joined), sampled pairs and triples of emoji,
  fuzzed strings built from emoji, truncated and mutated emoji, ZWJ, VS15/VS16, skin-tone and hair
  components, regional indicators, tag characters and keycaps, over all 14 languages, delimiters, `version`
  values, `handle_version` and both `keep_zwj` settings. About 8 million comparisons passed against emoji 2.16.0
  (0 failures); the same suite passes against 2.13.2.
* emoji's own test suite (102 tests) passes unchanged with `emoji_rs.patch()` applied.
* `tests/test_basic.py`: unit tests.

## License

BSD 3-Clause, same as emoji; see `LICENSE`.
