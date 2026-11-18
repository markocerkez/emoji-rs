"""Print the source digest of an installed ``emoji`` (used to extend VERIFIED_DIGESTS after
checking a new release against tests/diff_test.py).

    python tools/source_hashes.py            # digest of the emoji that is importable
    PYTHONPATH=/path/to/unpacked/emoji-wheel python tools/source_hashes.py
"""
import importlib.util
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "python" / "emoji_rs" / "_digest.py"
spec = importlib.util.spec_from_file_location("_digest", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
import emoji

print(getattr(emoji, "__version__", "?"), m.source_digest())
