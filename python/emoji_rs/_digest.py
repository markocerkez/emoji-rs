"""Digest of the ``emoji`` source that emoji-rs re-implements (kept free of other imports so that
``tools/source_hashes.py`` can load it on its own)."""
import hashlib
import inspect
import re

# Digests of emoji 2.13.2, 2.14.1, 2.15.0 and 2.16.0 (all identical for the ported functions).
VERIFIED_DIGESTS = {"ea1a94fb178bfc69"}


def source_digest() -> str:
    """Digest of the normalised source of everything this package re-implements."""
    import emoji.core as ec
    import emoji.tokenizer as tk

    h = hashlib.sha256()
    for mod, names in (
        (tk, ("tokenize", "filter_tokens")),
        (ec, ("demojize", "replace_emoji", "emoji_list", "distinct_emoji_list", "emoji_count",
              "purely_emoji", "analyze")),
    ):
        for n in names:
            src = inspect.getsource(getattr(mod, n))
            src = re.sub(r'""".*?"""', "", src, flags=re.S)
            h.update("\n".join(ln for ln in src.splitlines() if ln.strip()).encode())
    return h.hexdigest()[:16]
