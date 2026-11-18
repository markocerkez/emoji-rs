//! Rust port of the hot paths of the `emoji` package (tokenizer, `demojize`, `replace_emoji`,
//! `emoji_list`, `distinct_emoji_list`, `emoji_count`, `purely_emoji`).
//!
//! The tokenizer is a line-by-line port of `emoji.tokenizer.tokenize`, including its quirks
//! (greedy trie walk without backtracking, the `ignore` list for ZWJ characters, rewinding for
//! non-RGI ZWJ sequences, variation selectors being dropped). All data comes from the live
//! `EMOJI_DATA` of the installed `emoji` package, handed over by the Python wrapper.
#![allow(clippy::collapsible_match)]

use pyo3::exceptions::PyValueError;
use pyo3::marker::Ungil;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString};

const ZWJ: char = '\u{200d}';
const VS15: char = '\u{fe0e}';
const VS16: char = '\u{fe0f}';
const NONE: u32 = u32::MAX;
/// Direct lookup table for the first character of an emoji (all emoji start below this).
const ROOT_LIM: usize = 0x20000;

struct Node {
    kids: Vec<(char, u32)>,
    data: u32,
}

#[derive(Clone, Copy)]
enum Tok {
    Plain(char),
    Emoji { start: usize, end: usize, idx: u32 },
}

impl Tok {
    /// `len(token.chars)` in the Python implementation.
    fn len(&self) -> usize {
        match *self {
            Tok::Plain(_) => 1,
            Tok::Emoji { start, end, .. } => end - start,
        }
    }
}

enum Item {
    Plain(char),
    One {
        idx: u32,
        start: usize,
        end: usize,
    },
    /// Several emoji joined by ZWJ (`EmojiMatchZWJNonRGI`, whose `data` is None).
    Group,
}

/// Releasing the GIL costs more than the work for short strings.
const DETACH_MIN: usize = 20_000;

fn maybe_detach<T: Ungil + Send, F: FnOnce() -> T + Ungil + Send>(
    py: Python<'_>,
    len: usize,
    f: F,
) -> T {
    if len >= DETACH_MIN {
        py.detach(f)
    } else {
        f()
    }
}

#[pyclass]
struct Core {
    root: Vec<u32>,
    nodes: Vec<Node>,
    e: Vec<f64>,
    status: Vec<i64>,
    component: i64,
    names: std::collections::HashMap<String, Vec<Option<String>>>,
    aliases: Vec<Option<String>>,
}

/// `s[1:-1]` on code points.
fn strip_delims(s: &str) -> String {
    let cs: Vec<char> = s.chars().collect();
    if cs.len() < 2 {
        String::new()
    } else {
        cs[1..cs.len() - 1].iter().collect()
    }
}

impl Core {
    #[inline]
    fn root_child(&self, c: char) -> Option<u32> {
        let cp = c as usize;
        if cp < ROOT_LIM {
            let n = self.root[cp];
            if n != NONE {
                return Some(n);
            }
        }
        None
    }

    #[inline]
    fn child(&self, node: u32, c: char) -> Option<u32> {
        let kids = &self.nodes[node as usize].kids;
        if kids.len() <= 8 {
            for &(k, n) in kids {
                if k == c {
                    return Some(n);
                }
            }
            None
        } else {
            kids.binary_search_by(|&(k, _)| k.cmp(&c))
                .ok()
                .map(|i| kids[i].1)
        }
    }

    /// `token.chars in EMOJI_DATA` plus the index of that entry.
    fn emoji_idx(&self, t: &Tok) -> Option<u32> {
        match *t {
            Tok::Emoji { idx, .. } => Some(idx),
            Tok::Plain(c) => {
                let n = self.root_child(c)?;
                let d = self.nodes[n as usize].data;
                if d == NONE {
                    None
                } else {
                    Some(d)
                }
            }
        }
    }

    /// Port of `emoji.tokenizer.tokenize`, streaming: finished tokens are handed to `sink` in
    /// order (the Python generator yields them at the same points, so `result` - the pending tail
    /// that a ZWJ may still rewind - is identical). `sink` returning false stops early.
    ///
    /// Returns `None` when the original would behave in a way that is not reproduced here
    /// (the caller then uses the original), `Some(false)` when stopped by the sink.
    fn scan<F: FnMut(Tok) -> bool>(
        &self,
        s: &[char],
        keep_zwj: bool,
        sink: &mut F,
    ) -> Option<bool> {
        let n = s.len();
        let mut result: Vec<Tok> = Vec::new();
        let mut ignore = vec![false; n];
        let mut i: usize = 0;
        while i < n {
            let mut consumed = false;
            let c = s[i];
            if ignore[i] {
                i += 1;
                if c == ZWJ && keep_zwj {
                    result.push(Tok::Plain(c));
                }
                continue;
            } else if let Some(first) = self.root_child(c) {
                let mut j = i + 1;
                let mut node = first;
                while j < n {
                    match self.child(node, s[j]) {
                        Some(nx) => {
                            if ignore[j] {
                                break;
                            }
                            node = nx;
                            j += 1;
                        }
                        None => break,
                    }
                }
                let d = self.nodes[node as usize].data;
                if d != NONE {
                    result.push(Tok::Emoji {
                        start: i,
                        end: j,
                        idx: d,
                    });
                    i = j - 1;
                    consumed = true;
                }
            } else if c == ZWJ
                && i > 0
                && result.last().is_some_and(|t| self.emoji_idx(t).is_some())
                && self.root_child(s[i - 1]).is_some()
            {
                ignore[i] = true;
                let last = *result.last().unwrap();
                let last_idx = self.emoji_idx(&last).unwrap();
                if self.status[last_idx as usize] == self.component {
                    let k = result.len().min(2);
                    let sum: usize = result[result.len() - k..].iter().map(|t| t.len()).sum();
                    if sum > i {
                        return None; // Python would index with a negative position
                    }
                    i -= sum;
                    if s[i] == ZWJ {
                        i += 1;
                        result.pop();
                    } else {
                        let keep = result.len() - k;
                        result.truncate(keep);
                    }
                } else {
                    i -= last.len();
                    result.pop();
                }
                continue;
            } else if !result.is_empty() {
                for t in result.drain(..) {
                    if !sink(t) {
                        return Some(false);
                    }
                }
            }
            if !consumed && c != VS15 && c != VS16 {
                result.push(Tok::Plain(c));
            }
            i += 1;
        }
        for t in result {
            if !sink(t) {
                return Some(false);
            }
        }
        Some(true)
    }

    fn tokenize(&self, s: &[char], keep_zwj: bool) -> Option<Vec<Tok>> {
        let mut out = Vec::new();
        self.scan(s, keep_zwj, &mut |t| {
            out.push(t);
            true
        })?;
        Some(out)
    }

    /// `filter_tokens(tokens, emoji_only=False, join_emoji=True)`.
    fn join(&self, toks: &[Tok]) -> Vec<Item> {
        let mut items: Vec<Item> = Vec::with_capacity(toks.len());
        let mut acc: Vec<Item> = Vec::new();
        let (mut prev_emoji, mut prev_zwj) = (false, false);
        for t in toks {
            let pre = prev_emoji;
            match *t {
                Tok::Plain(ZWJ) if prev_emoji => prev_zwj = true,
                Tok::Emoji { idx, start, end } => {
                    if pre && prev_zwj {
                        if let Some(last) = acc.last_mut() {
                            *last = Item::Group;
                        }
                    } else {
                        acc.push(Item::One { idx, start, end });
                    }
                    prev_emoji = true;
                    prev_zwj = false;
                }
                Tok::Plain(c) => {
                    prev_emoji = false;
                    prev_zwj = false;
                    items.append(&mut acc);
                    items.push(Item::Plain(c));
                }
            }
        }
        items.append(&mut acc);
        items
    }
}

#[pymethods]
impl Core {
    #[new]
    fn new(keys: Vec<String>, e: Vec<f64>, status: Vec<i64>, component: i64) -> PyResult<Self> {
        if keys.len() != e.len() || keys.len() != status.len() {
            return Err(PyValueError::new_err("length mismatch"));
        }
        let mut nodes = vec![Node {
            kids: Vec::new(),
            data: NONE,
        }];
        for (idx, key) in keys.iter().enumerate() {
            let mut cur = 0usize;
            for c in key.chars() {
                let found = nodes[cur]
                    .kids
                    .iter()
                    .find(|&&(k, _)| k == c)
                    .map(|&(_, n)| n);
                cur = match found {
                    Some(n) => n as usize,
                    None => {
                        nodes.push(Node {
                            kids: Vec::new(),
                            data: NONE,
                        });
                        let id = (nodes.len() - 1) as u32;
                        nodes[cur].kids.push((c, id));
                        id as usize
                    }
                };
            }
            nodes[cur].data = idx as u32;
        }
        for nd in nodes.iter_mut() {
            nd.kids.sort_by_key(|&(k, _)| k);
        }
        let mut root = vec![NONE; ROOT_LIM];
        for &(k, n) in &nodes[0].kids {
            if (k as usize) < ROOT_LIM {
                root[k as usize] = n;
            } else {
                return Err(PyValueError::new_err("emoji outside the supported range"));
            }
        }
        let n = keys.len();
        Ok(Core {
            root,
            nodes,
            e,
            status,
            component,
            names: Default::default(),
            aliases: vec![None; n],
        })
    }

    /// `names[i]` is `EMOJI_DATA[key_i].get(lang)` (e.g. ":thumbs_up:") or None.
    fn set_names(&mut self, lang: String, names: Vec<Option<String>>) -> PyResult<()> {
        if names.len() != self.e.len() {
            return Err(PyValueError::new_err("length mismatch"));
        }
        let inner = names
            .iter()
            .map(|o| o.as_deref().map(strip_delims))
            .collect();
        self.names.insert(lang, inner);
        Ok(())
    }

    /// `aliases[i]` is `EMOJI_DATA[key_i]['alias'][0]` or None.
    fn set_aliases(&mut self, aliases: Vec<Option<String>>) -> PyResult<()> {
        if aliases.len() != self.e.len() {
            return Err(PyValueError::new_err("length mismatch"));
        }
        self.aliases = aliases
            .iter()
            .map(|o| o.as_deref().map(strip_delims))
            .collect();
        Ok(())
    }

    fn has_language(&self, lang: &str) -> bool {
        self.names.contains_key(lang)
    }

    #[allow(clippy::too_many_arguments)]
    fn demojize(
        &self,
        py: Python<'_>,
        string: String,
        d0: String,
        d1: String,
        lang: &str,
        use_alias: bool,
        version: Option<f64>,
        handle_version: Option<String>,
        keep_zwj: bool,
    ) -> Option<String> {
        let names = self.names.get(lang)?;
        let len = string.len();
        maybe_detach(py, len, || {
            let s: Vec<char> = string.chars().collect();
            let mut out = String::with_capacity(string.len());
            self.scan(&s, keep_zwj, &mut |t| {
                match t {
                    Tok::Plain(c) => out.push(c),
                    Tok::Emoji { start, end, idx } => {
                        let k = idx as usize;
                        if version.is_some_and(|v| self.e[k] > v) {
                            if let Some(h) = &handle_version {
                                out.push_str(h);
                            }
                        } else if let Some(nm) = &names[k] {
                            out.push_str(&d0);
                            match (use_alias, &self.aliases[k]) {
                                (true, Some(a)) => out.push_str(a),
                                _ => out.push_str(nm),
                            }
                            out.push_str(&d1);
                        } else {
                            out.extend(&s[start..end]);
                        }
                    }
                }
                true
            })?;
            Some(out)
        })
    }

    fn replace_emoji(
        &self,
        py: Python<'_>,
        string: String,
        replace: String,
        version: f64,
        keep_zwj: bool,
    ) -> Option<String> {
        let len = string.len();
        maybe_detach(py, len, || {
            let s: Vec<char> = string.chars().collect();
            let mut out = String::with_capacity(string.len());
            let versioned = version > -1.0;
            let one = |out: &mut String, start: usize, end: usize, idx: u32| {
                if versioned {
                    if self.e[idx as usize] > version {
                        out.push_str(&replace);
                    } else {
                        out.extend(&s[start..end]);
                    }
                } else {
                    out.push_str(&replace);
                }
            };
            if keep_zwj {
                let toks = self.tokenize(&s, true)?;
                for it in self.join(&toks) {
                    match it {
                        Item::Plain(c) => out.push(c),
                        Item::One { idx, start, end } => one(&mut out, start, end, idx),
                        Item::Group => {
                            if versioned {
                                return None; // original asserts on data=None
                            }
                            out.push_str(&replace);
                        }
                    }
                }
                Some(out)
            } else {
                self.scan(&s, false, &mut |t| {
                    match t {
                        Tok::Plain(c) => out.push(c),
                        Tok::Emoji { start, end, idx } => one(&mut out, start, end, idx),
                    }
                    true
                })?;
                Some(out)
            }
        })
    }

    fn emoji_list<'py>(
        &self,
        py: Python<'py>,
        string: String,
    ) -> PyResult<Option<Bound<'py, PyList>>> {
        let s: Vec<char> = string.chars().collect();
        let Some(spans) = maybe_detach(py, s.len(), || {
            let mut spans = Vec::new();
            self.scan(&s, false, &mut |t| {
                if let Tok::Emoji { start, end, .. } = t {
                    spans.push((start, end));
                }
                true
            })?;
            Some(spans)
        }) else {
            return Ok(None);
        };
        let k_start = PyString::new(py, "match_start");
        let k_end = PyString::new(py, "match_end");
        let k_emoji = PyString::new(py, "emoji");
        let list = PyList::empty(py);
        for (start, end) in spans {
            let d = PyDict::new(py);
            d.set_item(&k_start, start)?;
            d.set_item(&k_end, end)?;
            let e: String = s[start..end].iter().collect();
            d.set_item(&k_emoji, e)?;
            list.append(d)?;
        }
        Ok(Some(list))
    }

    /// The emoji strings in order of appearance (duplicates kept).
    fn emoji_strings<'py>(
        &self,
        py: Python<'py>,
        string: String,
    ) -> PyResult<Option<Bound<'py, PyList>>> {
        let s: Vec<char> = string.chars().collect();
        let Some(strs) = maybe_detach(py, s.len(), || {
            let mut v: Vec<String> = Vec::new();
            self.scan(&s, false, &mut |t| {
                if let Tok::Emoji { start, end, .. } = t {
                    v.push(s[start..end].iter().collect());
                }
                true
            })?;
            Some(v)
        }) else {
            return Ok(None);
        };
        Ok(Some(PyList::new(py, strs)?))
    }

    fn emoji_count(&self, py: Python<'_>, string: String) -> Option<usize> {
        let len = string.len();
        maybe_detach(py, len, || {
            let s: Vec<char> = string.chars().collect();
            let mut n = 0usize;
            self.scan(&s, false, &mut |t| {
                n += matches!(t, Tok::Emoji { .. }) as usize;
                true
            })?;
            Some(n)
        })
    }

    fn purely_emoji(&self, py: Python<'_>, string: String) -> Option<bool> {
        let len = string.len();
        maybe_detach(py, len, || {
            let s: Vec<char> = string.chars().collect();
            // `all(isinstance(m.value, EmojiMatch) for m in analyze(string, non_emoji=True))`: a
            // joined group counts as an emoji, and a ZWJ right after an emoji is swallowed.
            let mut prev_emoji = false;
            let done = self.scan(&s, true, &mut |t| match t {
                Tok::Emoji { .. } => {
                    prev_emoji = true;
                    true
                }
                Tok::Plain(ZWJ) if prev_emoji => true,
                Tok::Plain(_) => false,
            })?;
            Some(done)
        })
    }
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Core>()?;
    Ok(())
}
