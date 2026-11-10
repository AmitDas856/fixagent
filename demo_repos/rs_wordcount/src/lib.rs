//! Word counting helpers.

use std::collections::HashMap;

/// Count the words in a piece of text. Words are separated by whitespace.
pub fn word_count(text: &str) -> usize {
    text.split(' ').count()
}

/// Count how many times each word appears, ignoring case.
pub fn word_frequencies(text: &str) -> HashMap<String, usize> {
    let mut counts = HashMap::new();
    for word in text.split_whitespace() {
        *counts.entry(word.to_lowercase()).or_insert(0) += 1;
    }
    counts
}

/// Return the longest word in the text, or `None` if there are no words.
pub fn longest_word(text: &str) -> Option<&str> {
    text.split_whitespace().max_by_key(|word| word.len())
}
