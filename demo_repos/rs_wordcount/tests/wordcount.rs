use wordcount::{longest_word, word_count, word_frequencies};

#[test]
fn counts_simple_sentence() {
    assert_eq!(word_count("the quick brown fox"), 4);
}

#[test]
fn counts_with_repeated_spaces() {
    assert_eq!(word_count("the  quick   brown fox"), 4);
}

#[test]
fn counts_with_tabs_and_newlines() {
    assert_eq!(word_count("one\ttwo\nthree"), 3);
}

#[test]
fn empty_text_has_no_words() {
    assert_eq!(word_count(""), 0);
    assert_eq!(word_count("   "), 0);
}

#[test]
fn frequencies_ignore_case() {
    let counts = word_frequencies("Rust rust RUST go");
    assert_eq!(counts["rust"], 3);
    assert_eq!(counts["go"], 1);
}

#[test]
fn finds_longest_word() {
    assert_eq!(longest_word("a bbb cc"), Some("bbb"));
    assert_eq!(longest_word(""), None);
}
