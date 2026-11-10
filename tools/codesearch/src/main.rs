//! codesearch: literal, case-sensitive text search over a directory tree.
//!
//! Usage: codesearch <pattern> <path>
//!
//! Prints one `path:line:text` row per matching line, with files visited in
//! sorted order. Build and dependency directories are skipped, and files that
//! are not valid UTF-8 are ignored. Exit code is 0 when something matched,
//! 1 when nothing matched and 2 on a usage or I/O error.
//!
//! It uses only the standard library, so it builds with no network access.

use std::env;
use std::fs;
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const IGNORED_DIRS: [&str; 8] = [
    ".git",
    "__pycache__",
    ".pytest_cache",
    "target",
    "build",
    "node_modules",
    ".venv",
    "venv",
];

fn is_ignored(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .map(|name| IGNORED_DIRS.contains(&name))
        .unwrap_or(false)
}

/// Collect every file under `root`, depth first, in sorted order.
fn collect_files(root: &Path, files: &mut Vec<PathBuf>) -> io::Result<()> {
    if root.is_file() {
        files.push(root.to_path_buf());
        return Ok(());
    }
    let mut entries: Vec<PathBuf> = fs::read_dir(root)?
        .filter_map(|entry| entry.ok().map(|e| e.path()))
        .collect();
    entries.sort();
    // Files first, then subdirectories, to match the Python fallback's order.
    for path in entries.iter().filter(|p| p.is_file()) {
        files.push(path.clone());
    }
    for path in entries.iter().filter(|p| p.is_dir()) {
        if !is_ignored(path) {
            collect_files(path, files)?;
        }
    }
    Ok(())
}

/// Return the `(line number, trimmed line)` pairs of `text` containing `pattern`.
fn matching_lines<'a>(text: &'a str, pattern: &str) -> Vec<(usize, &'a str)> {
    text.lines()
        .enumerate()
        .filter(|(_, line)| line.contains(pattern))
        .map(|(index, line)| (index + 1, line.trim()))
        .collect()
}

fn run(pattern: &str, root: &Path) -> io::Result<usize> {
    let mut files = Vec::new();
    collect_files(root, &mut files)?;

    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());
    let mut total = 0;
    for file in files {
        // Skip binaries and anything else that is not valid UTF-8.
        let Ok(text) = fs::read_to_string(&file) else {
            continue;
        };
        for (number, line) in matching_lines(&text, pattern) {
            writeln!(out, "{}:{}:{}", file.display(), number, line)?;
            total += 1;
        }
    }
    out.flush()?;
    Ok(total)
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 || args[1].is_empty() {
        eprintln!("usage: codesearch <pattern> <path>");
        return ExitCode::from(2);
    }
    match run(&args[1], Path::new(&args[2])) {
        Ok(0) => ExitCode::from(1),
        Ok(_) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("codesearch: {error}");
            ExitCode::from(2)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_lines_with_numbers() {
        let text = "fn main() {\n    let total = 1;\n}\nlet total = 2;";
        assert_eq!(
            matching_lines(text, "total"),
            vec![(2, "let total = 1;"), (4, "let total = 2;")]
        );
    }

    #[test]
    fn search_is_case_sensitive() {
        assert!(matching_lines("Total", "total").is_empty());
    }

    #[test]
    fn ignores_build_directories() {
        assert!(is_ignored(Path::new("project/target")));
        assert!(is_ignored(Path::new(".git")));
        assert!(!is_ignored(Path::new("project/src")));
    }
}
