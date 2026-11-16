//! Native hot-path helpers for G-Bible.
//!
//! The Python application remains the compatibility layer and public API.  This
//! crate deliberately implements small, deterministic primitives that are used
//! repeatedly by indexing and search; format-specific parsing and database
//! orchestration stay in Python until each format can be migrated with parity
//! tests of its own.

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::{PyBytes, PyModule};
use unicode_general_category::{get_general_category, GeneralCategory as GC};
use unicode_normalization::UnicodeNormalization;

fn is_letter(c: char) -> bool {
    matches!(get_general_category(c),
        GC::UppercaseLetter | GC::LowercaseLetter | GC::TitlecaseLetter |
        GC::ModifierLetter | GC::OtherLetter | GC::LetterNumber | GC::OtherNumber)
}

fn is_token_mark(c: char) -> bool {
    let n = c as u32;
    matches!(n,
        0x0300..=0x036f | 0x0483..=0x0489 |
        0x0591..=0x05c7 | 0x05bd | 0x05bf | 0x05c1 | 0x05c2 | 0x05c4 | 0x05c5 |
        0x064b..=0x0652 | 0x065f | 0x06d6..=0x06dc |
        0x0e31 | 0x0e34..=0x0e3a | 0x1ab0..=0x1aff | 0x1dc0..=0x1dff |
        0x20d0..=0x20ff | 0xfe20..=0xfe2f)
}

fn is_combining(c: char) -> bool {
    unicode_normalization::char::canonical_combining_class(c) != 0
}

fn is_decimal(c: char) -> bool {
    get_general_category(c) == GC::DecimalNumber
}

/// Python-compatible word tokens with Unicode-character (not UTF-8-byte) offsets.
#[pyfunction]
fn words(text: &str) -> Vec<(String, usize, usize)> {
    let chars: Vec<char> = text.chars().collect();
    let mut out = Vec::new();
    let mut i = 0usize;
    while i < chars.len() {
        if is_letter(chars[i]) {
            let start = i;
            i += 1;
            while i < chars.len() && (is_letter(chars[i]) || is_token_mark(chars[i])) {
                i += 1;
            }
            // Match the application's internal-apostrophe rule: an apostrophe
            // is part of a word only when another letter follows it.
            loop {
                if i + 1 < chars.len()
                    && (chars[i] == '\'' || chars[i] == '\u{2019}')
                    && is_letter(chars[i + 1])
                {
                    i += 2;
                    while i < chars.len() && (is_letter(chars[i]) || is_token_mark(chars[i])) {
                        i += 1;
                    }
                } else {
                    break;
                }
            }
            out.push((chars[start..i].iter().collect(), start, i));
        } else if is_decimal(chars[i]) {
            let start = i;
            i += 1;
            while i < chars.len() && is_decimal(chars[i]) { i += 1; }
            out.push((chars[start..i].iter().collect(), start, i));
        } else {
            i += 1;
        }
    }
    out
}

fn folded_char(c: char) -> char {
    match c {
        '\u{2019}' | '\u{02bc}' | '\u{2018}' => '\'',
        '\u{201c}' | '\u{201d}' => '"',
        '\u{2013}' | '\u{2014}' => '-',
        _ => c,
    }
}


fn entity_value(name: &str) -> Option<&'static str> {
    Some(match name {
        "amp" => "&", "lt" => "<", "gt" => ">", "quot" => "\"", "apos" => "'",
        "nbsp" => "\u{00a0}", "ndash" => "\u{2013}", "mdash" => "\u{2014}",
        "hellip" => "\u{2026}", "lsquo" => "\u{2018}", "rsquo" => "\u{2019}",
        "ldquo" => "\u{201c}", "rdquo" => "\u{201d}", "deg" => "\u{00b0}",
        "middot" => "\u{00b7}", "bull" => "\u{2022}", "dagger" => "\u{2020}",
        "sect" => "\u{00a7}", "para" => "\u{00b6}", "copy" => "\u{00a9}",
        "reg" => "\u{00ae}", "trade" => "\u{2122}", "prime" => "\u{2032}",
        "Prime" => "\u{2033}", "larr" => "\u{2190}", "rarr" => "\u{2192}",
        "harr" => "\u{2194}", "times" => "\u{00d7}", "divide" => "\u{00f7}",
        "minus" => "\u{2212}", "plusmn" => "\u{00b1}", "frac12" => "\u{00bd}",
        "sup1" => "\u{00b9}", "sup2" => "\u{00b2}", "sup3" => "\u{00b3}", "sup4" => "\u{2074}",
        "eacute" => "\u{00e9}", "egrave" => "\u{00e8}", "ecirc" => "\u{00ea}", "agrave" => "\u{00e0}",
        "ccedil" => "\u{00e7}", "uuml" => "\u{00fc}", "ouml" => "\u{00f6}", "auml" => "\u{00e4}",
        "szlig" => "\u{00df}", "ntilde" => "\u{00f1}", "aacute" => "\u{00e1}", "iacute" => "\u{00ed}",
        "oacute" => "\u{00f3}", "uacute" => "\u{00fa}", "aring" => "\u{00e5}", "oslash" => "\u{00f8}",
        "aelig" => "\u{00e6}", "curren" => "\u{00a4}", "percnt" => "%", "vert" => "|",
        "sol" => "/", "commat" => "@", "lowbar" => "_", "num" => "#", "dollar" => "$",
        "excl" => "!", "quest" => "?", "lpar" => "(", "rpar" => ")", "ast" => "*",
        "period" => ".", "comma" => ",", "semi" => ";", "colon" => ":",
        "zwj" => "\u{200d}", "zwnj" => "\u{200c}", "shy" => "\u{00ad}",
        _ => return None,
    })
}

#[pyfunction]
fn unescape_entities(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut i = 0usize;
    while i < bytes.len() {
        if bytes[i] != b'&' {
            let ch = text[i..].chars().next().unwrap();
            out.push(ch);
            i += ch.len_utf8();
            continue;
        }

        // Match the same restricted entity grammar as Python's _ENTITY_RE.
        // Stop at the first invalid character so a later nested '&name;' can
        // still be recognised on the next pass through the input.
        let start = i + 1;
        let mut end = start;
        let numeric = bytes.get(start) == Some(&b'#');
        let mut radix = 10u32;
        if numeric {
            end += 1;
            if bytes.get(end) == Some(&b'x') { radix = 16; end += 1; }
            let digits = end;
            while bytes.get(end).is_some_and(|b| b.is_ascii_hexdigit()) { end += 1; }
            if end == digits || bytes.get(end) != Some(&b';') {
                out.push('&'); i += 1; continue;
            }
        } else {
            if !bytes.get(end).is_some_and(|b| b.is_ascii_alphabetic()) {
                out.push('&'); i += 1; continue;
            }
            end += 1;
            while bytes.get(end).is_some_and(|b| b.is_ascii_alphanumeric()) { end += 1; }
            if bytes.get(end) != Some(&b';') {
                out.push('&'); i += 1; continue;
            }
        }

        let name = &text[start..end];
        let decoded = if numeric {
            let digits = if radix == 16 { &name[2..] } else { &name[1..] };
            u32::from_str_radix(digits, radix).ok().and_then(char::from_u32).map(|c| c.to_string())
        } else {
            entity_value(name).or_else(|| entity_value(&name.to_ascii_lowercase())).map(|v| v.to_string())
        };
        if let Some(value) = decoded {
            out.push_str(&value);
        } else {
            out.push_str(&text[i..=end]);
        }
        i = end + 1;
    }
    out
}

#[pyfunction]
fn collapse_spaces(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut in_run = false;
    for c in text.chars() {
        if c == ' ' || c == '\t' || c == '\u{00a0}' {
            if !in_run { out.push(' '); in_run = true; }
        } else {
            out.push(c);
            in_run = false;
        }
    }
    out
}

#[pyfunction]
fn fold(word: &str) -> String {
    let lowered: String = word.chars().flat_map(|c| c.to_lowercase()).map(folded_char).collect();
    lowered.nfd().filter(|c| !is_combining(*c)).collect()
}

const NO_STEM: &[&str] = &[
    "this", "his", "her", "its", "their", "ours", "yours", "was", "were", "been",
    "being", "has", "had", "having", "does", "did", "doing", "is", "are", "am",
    "be", "as", "us", "them", "him", "who", "whom", "whose", "which", "what",
    "shall", "should", "will", "would", "can", "could", "may", "might", "must",
    "he", "she", "they", "we", "you", "i", "it", "not", "no", "nor", "but", "and",
    "or", "if", "then", "than", "that", "so", "such", "there", "here", "when",
    "where", "while", "unto", "upon",
];

fn stem_inner(input: &str, depth: usize) -> String {
    if depth > 24 { return input.to_string(); }
    let mut w = input.to_lowercase();
    if w.chars().count() <= 3 || NO_STEM.contains(&w.as_str()) { return w; }
    if let Some(base) = w.strip_suffix("'s").or_else(|| w.strip_suffix("\u{2019}s")) {
        w = base.to_string();
    }
    if w.chars().count() <= 3 { return w; }
    let recurse = |s: &str| stem_inner(s, depth + 1);
    if w.ends_with("ies") && w.chars().count() > 4 {
        return recurse(&format!("{}y", &w[..w.len()-3]));
    }
    if ["sses", "shes", "ches", "xes"].iter().any(|s| w.ends_with(s)) {
        return recurse(&w[..w.len()-2]);
    }
    if w.ends_with("ss") { return w; }
    if w.ends_with('s') && !w.ends_with("us") && !w.ends_with("is") {
        return recurse(&w[..w.len()-1]);
    }
    for suf in ["ingly", "edly"] {
        if w.ends_with(suf) && w.chars().count() > suf.chars().count() + 3 {
            return recurse(&w[..w.len()-suf.len()]);
        }
    }
    if w.ends_with("ing") && w.chars().count() > 5 {
        let mut base = w[..w.len()-3].to_string();
        let cs: Vec<char> = base.chars().collect();
        if cs.len() > 2 && cs[cs.len()-1] == cs[cs.len()-2]
            && !['l','s','z'].contains(&cs[cs.len()-1]) {
            base.pop();
        }
        if ["bl", "at", "iz", "iv", "us", "ur", "os", "io", "ia"].iter().any(|s| base.ends_with(s)) {
            base.push('e');
        }
        return recurse(&base);
    }
    if w.ends_with("ied") && w.chars().count() > 4 {
        return recurse(&format!("{}y", &w[..w.len()-3]));
    }
    if w.ends_with("ed") && w.chars().count() > 4 {
        let mut base = w[..w.len()-2].to_string();
        let cs: Vec<char> = base.chars().collect();
        if cs.len() > 2 && cs[cs.len()-1] == cs[cs.len()-2]
            && !['l','s','z'].contains(&cs[cs.len()-1]) {
            base.pop();
        }
        return recurse(&base);
    }
    if w.ends_with("ly") && w.chars().count() > 4 { return recurse(&w[..w.len()-2]); }
    if w.ends_with("er") && w.chars().count() > 5 { return recurse(&w[..w.len()-2]); }
    if w.ends_with("est") && w.chars().count() > 6 { return recurse(&w[..w.len()-3]); }
    if w.ends_with("ness") && w.chars().count() > 6 { return recurse(&w[..w.len()-4]); }
    if w.ends_with("ment") && w.chars().count() > 7 { return recurse(&w[..w.len()-4]); }
    if w.ends_with("tion") && w.chars().count() > 6 { return recurse(&w[..w.len()-3]); }
    let cs: Vec<char> = w.chars().collect();
    if cs.len() > 3 && cs.last() == Some(&'e') && !"aeiou".contains(cs[cs.len()-2]) {
        w.pop();
    }
    w
}

#[pyfunction]
fn stem(word: &str) -> String { stem_inner(word, 0) }

#[pyfunction]
fn token_key(word: &str) -> String { stem(&fold(word)) }

#[pyfunction]
fn pack_positions<'py>(py: Python<'py>, positions: Vec<usize>, max_pos: usize) -> PyResult<Bound<'py, PyBytes>> {
    let mut out = Vec::new();
    let mut prev: Option<u64> = None;
    for p in positions.iter().take(max_pos) {
        let current = *p as u64;
        let delta = match prev {
            Some(last) if current <= last => return Err(PyValueError::new_err(
                format!("positions must be strictly increasing: {current} after {last}"))),
            Some(last) => current - last - 1,
            None => current,
        };
        let mut n = delta;
        loop {
            let b = (n & 0x7f) as u8;
            n >>= 7;
            if n != 0 { out.push(b | 0x80); } else { out.push(b); break; }
        }
        prev = Some(current);
    }
    Ok(PyBytes::new(py, &out))
}

#[pyfunction]
fn unpack_varints(buf: &Bound<'_, PyBytes>) -> Vec<u64> {
    let mut out = Vec::new();
    let mut val = 0u64;
    let mut shift = 0u32;
    for byte in buf.as_bytes() {
        if shift >= 64 { break; }
        val |= ((byte & 0x7f) as u64).checked_shl(shift).unwrap_or(0);
        if byte & 0x80 != 0 { shift += 7; }
        else { out.push(val); val = 0; shift = 0; }
    }
    out
}

#[pyfunction]
fn damerau_levenshtein(a: &str, b: &str, cap: usize) -> usize {
    if a == b { return 0; }
    let aa: Vec<char> = a.chars().collect();
    let bb: Vec<char> = b.chars().collect();
    if aa.len().abs_diff(bb.len()) > cap { return cap + 1; }
    let mut prev2: Vec<usize> = Vec::new();
    let mut prev: Vec<usize> = (0..=bb.len()).collect();
    for i in 1..=aa.len() {
        let mut cur = vec![i; bb.len() + 1];
        for j in 1..=bb.len() {
            cur[j] = (prev[j] + 1).min(cur[j-1] + 1).min(prev[j-1] + if aa[i-1] != bb[j-1] { 1 } else { 0 });
            if i > 1 && j > 1 && aa[i-1] == bb[j-2] && aa[i-2] == bb[j-1] {
                cur[j] = cur[j].min(prev2[j-2] + 1);
            }
        }
        if *cur.iter().min().unwrap_or(&0) > cap { return cap + 1; }
        prev2 = prev;
        prev = cur;
    }
    *prev.last().unwrap_or(&0)
}

#[pymodule]
fn _gbible_rust_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(words, m)?)?;
    m.add_function(wrap_pyfunction!(unescape_entities, m)?)?;
    m.add_function(wrap_pyfunction!(collapse_spaces, m)?)?;
    m.add_function(wrap_pyfunction!(fold, m)?)?;
    m.add_function(wrap_pyfunction!(stem, m)?)?;
    m.add_function(wrap_pyfunction!(token_key, m)?)?;
    m.add_function(wrap_pyfunction!(pack_positions, m)?)?;
    m.add_function(wrap_pyfunction!(unpack_varints, m)?)?;
    m.add_function(wrap_pyfunction!(damerau_levenshtein, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn folding_and_stemming_match_core_examples() {
        assert_eq!(fold("JESUS’"), "jesus'");
        assert_eq!(stem("loves"), "lov");
        assert_eq!(stem("loved"), "lov");
        assert_eq!(stem("prayer"), "pray");
        assert_eq!(unescape_entities("&amp; &Prime; &#65;"), "& \u{2033} A");
        assert_eq!(unescape_entities("&bad&copy;"), "&bad\u{00a9}");
        assert_eq!(collapse_spaces("a \t\u{00a0} b"), "a b");
    }
    #[test]
    fn token_offsets_are_character_offsets() {
        let got = words("שלום, God's 123");
        assert_eq!(got[0], ("שלום".to_string(), 0, 4));
        assert_eq!(got[1], ("God's".to_string(), 6, 11));
        assert_eq!(got[2], ("123".to_string(), 12, 15));
    }
}
