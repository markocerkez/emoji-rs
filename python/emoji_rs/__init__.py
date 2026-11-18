"""Rust-accelerated ``demojize``, ``replace_emoji`` and ``emoji_list`` for the ``emoji`` package.

Usage::

    import emoji, emoji_rs
    emoji_rs.patch()      # emoji.demojize / replace_emoji / emoji_list / ... now use Rust
    emoji_rs.unpatch()    # restore the original implementation

or call ``emoji_rs.demojize`` etc. directly. Anything the Rust core does not handle (callables
for ``replace`` / ``handle_version``, non-``str`` arguments, modified ``EMOJI_DATA``, an ``emoji``
release whose tokenizer differs from the verified one, ...) is passed to the original function, so
results are identical.
"""
from __future__ import annotations

import functools
import warnings

import emoji as _emoji
import emoji.core as _ec
import emoji.tokenizer as _tk
import emoji.unicode_codes as _uc

from . import _core
from ._digest import VERIFIED_DIGESTS as _VERIFIED_DIGESTS, source_digest

__all__ = [
    "patch", "unpatch", "is_patched", "refresh",
    "demojize", "replace_emoji", "emoji_list", "distinct_emoji_list", "emoji_count", "purely_emoji",
]

_FALLBACK = (TypeError, ValueError, UnicodeError, OverflowError)
_NUM = (int, float)

# The ported algorithms are identical in emoji 2.13.2 - 2.16.0. For other releases the normalised
# source of the ported functions is hashed (``_digest.py``, ``tools/source_hashes.py``) and the fast
# path stays off unless the digest matches a verified one.
_VERIFIED_VERSIONS = {"2.13.2", "2.14.1", "2.15.0", "2.16.0"}

_orig = {
    "demojize": _ec.demojize,
    "replace_emoji": _ec.replace_emoji,
    "emoji_list": _ec.emoji_list,
    "distinct_emoji_list": _ec.distinct_emoji_list,
    "emoji_count": _ec.emoji_count,
    "purely_emoji": _ec.purely_emoji,
}
_orig_load = _uc.load_from_json


_VERIFIED_DIGESTS = set(_VERIFIED_DIGESTS)


def _supported() -> bool:
    try:
        return source_digest() in _VERIFIED_DIGESTS
    except (OSError, TypeError):  # no source available (frozen app, .pyc only)
        return getattr(_emoji, "__version__", None) in _VERIFIED_VERSIONS


class _State:
    core = None
    data = None
    n = -1
    alias_ok = True


def _build() -> None:
    """(Re)build the Rust tables from the live ``EMOJI_DATA``."""
    st = _State
    st.core = st.data = None
    st.n = -1
    if not _supported():
        return
    try:
        data = _uc.EMOJI_DATA
        vals = list(data.values())
        core = _core.Core(
            list(data),
            [float(d["E"]) for d in vals],
            [int(d["status"]) for d in vals],
            int(_uc.STATUS["component"]),
        )
        st.alias_ok = all(d["alias"] for d in vals if "alias" in d)
        core.set_aliases([d["alias"][0] if d.get("alias") else None for d in vals])
        core.set_names("en", [d.get("en") for d in vals])
    except Exception:  # unexpected data layout: stay on the original implementation
        return
    st.core, st.data, st.n = core, data, len(data)


def _lang(core, lang: str) -> None:
    _orig_load(lang)  # raises exactly like the original for unknown languages
    core.set_names(lang, [d.get(lang) for d in _uc.EMOJI_DATA.values()])


def refresh() -> None:
    """Rebuild the Rust tables; call after modifying ``emoji.EMOJI_DATA`` in place."""
    _build()


def _live():
    st = _State
    core = st.core
    if core is not None and _uc.EMOJI_DATA is st.data and len(st.data) == st.n:
        return core
    return None


def _wrap(orig):
    def deco(fn):
        return functools.wraps(orig)(fn)
    return deco


@_wrap(_orig["demojize"])
def demojize(string, delimiters=(":", ":"), language="en", version=None, handle_version=None):
    core = _live()
    if (
        core is not None
        and type(string) is str
        and type(language) is str
        and type(delimiters) is tuple
        and len(delimiters) == 2
        and (version is None or type(version) in _NUM)
        and (handle_version is None or type(handle_version) is str)
    ):
        use_alias = language == "alias"
        lang = "en" if use_alias else language
        if (use_alias and not _State.alias_ok):
            return _orig["demojize"](string, delimiters, language, version, handle_version)
        if not core.has_language(lang):
            _lang(core, lang)
        try:
            r = core.demojize(
                string, delimiters[0], delimiters[1], lang, use_alias, version, handle_version,
                bool(_ec.config.demojize_keep_zwj),
            )
        except _FALLBACK:
            r = None
        if r is not None:
            return r
    return _orig["demojize"](string, delimiters, language, version, handle_version)


@_wrap(_orig["replace_emoji"])
def replace_emoji(string, replace="", version=-1):
    core = _live()
    if (
        core is not None
        and type(string) is str
        and type(replace) is str
        and type(version) in _NUM
    ):
        try:
            r = core.replace_emoji(string, replace, version, bool(_ec.config.replace_emoji_keep_zwj))
        except _FALLBACK:
            r = None
        if r is not None:
            return r
    return _orig["replace_emoji"](string, replace, version)


@_wrap(_orig["emoji_list"])
def emoji_list(string):
    core = _live()
    if core is not None and type(string) is str:
        try:
            r = core.emoji_list(string)
        except _FALLBACK:
            r = None
        if r is not None:
            return r
    return _orig["emoji_list"](string)


@_wrap(_orig["distinct_emoji_list"])
def distinct_emoji_list(string):
    core = _live()
    if core is not None and type(string) is str:
        try:
            r = core.emoji_strings(string)
        except _FALLBACK:
            r = None
        if r is not None:
            return list(set(r))  # same insertion order as the original set comprehension
    return _orig["distinct_emoji_list"](string)


@_wrap(_orig["emoji_count"])
def emoji_count(string, unique=False):
    core = _live()
    if core is not None and type(string) is str and type(unique) is bool:
        try:
            if unique:
                r = core.emoji_strings(string)
                r = None if r is None else len(set(r))
            else:
                r = core.emoji_count(string)
        except _FALLBACK:
            r = None
        if r is not None:
            return r
    return _orig["emoji_count"](string, unique)


@_wrap(_orig["purely_emoji"])
def purely_emoji(string):
    core = _live()
    if core is not None and type(string) is str:
        try:
            r = core.purely_emoji(string)
        except _FALLBACK:
            r = None
        if r is not None:
            return r
    return _orig["purely_emoji"](string)


_FUNCS = {
    "demojize": demojize,
    "replace_emoji": replace_emoji,
    "emoji_list": emoji_list,
    "distinct_emoji_list": distinct_emoji_list,
    "emoji_count": emoji_count,
    "purely_emoji": purely_emoji,
}


def patch() -> bool:
    """Make ``emoji.demojize`` & co. use the Rust core. Returns False (and changes nothing, with
    a warning) when the installed ``emoji`` is not a release this package has been verified against.
    Names imported earlier with ``from emoji import demojize`` keep pointing at the original."""
    if _State.core is None and not _supported():
        warnings.warn(
            "emoji-rs: the installed emoji package differs from the verified releases; "
            "not patching (the original implementation stays in use).",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    if _State.core is None:
        _build()
    for name, fn in _FUNCS.items():
        setattr(_ec, name, fn)
        setattr(_emoji, name, fn)
    return True


def unpatch() -> None:
    for name, fn in _orig.items():
        setattr(_ec, name, fn)
        setattr(_emoji, name, fn)


def is_patched() -> bool:
    return _ec.demojize is demojize


_build()
