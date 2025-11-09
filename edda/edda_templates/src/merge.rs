use imara_diff::{Algorithm, Diff, InternedInput, Interner, Token};

#[derive(Debug, Clone)]
pub struct ConflictInfo {
    pub base_line: u32,
    pub a_content: String,
    pub b_content: String,
}

impl ConflictInfo {
    pub fn marker_string(&self, marker_a: &str, marker_b: &str) -> String {
        let fmt = |c: &str| {
            if !c.ends_with('\n') {
                format!("{}\n", c)
            } else {
                c.to_string()
            }
        };
        let a_content = fmt(&self.a_content);
        let b_content = fmt(&self.b_content);
        format!(
            "<<<<<<< {}\n{}=======\n{}>>>>>>> {}\n",
            marker_a, a_content, b_content, marker_b
        )
    }
}

impl std::fmt::Display for ConflictInfo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Conflict at line {}:\n", self.base_line)?;
        for line in self.a_content.lines() {
            write!(f, "< {}\n", line)?;
        }
        write!(f, "===\n")?;
        for line in self.b_content.lines() {
            write!(f, "> {}\n", line)?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct Merger {
    pub marker_a: String,
    pub marker_b: String,
}

impl Merger {
    pub fn new(marker_a: &str, marker_b: &str) -> Self {
        Self {
            marker_a: marker_a.to_string(),
            marker_b: marker_b.to_string(),
        }
    }

    pub fn merge(&self, common: &str, a: &str, b: &str) -> MergeResult {
        let input_a = InternedInput::new(common, a);
        let mut diff_a = Diff::compute(Algorithm::Histogram, &input_a);
        diff_a.postprocess_lines(&input_a);

        let input_b = InternedInput::new(common, b);
        let mut diff_b = Diff::compute(Algorithm::Histogram, &input_b);
        diff_b.postprocess_lines(&input_b);

        #[derive(Debug, Clone, Copy)]
        enum Branch {
            A,
            B,
        }

        #[derive(Debug, Clone, Copy)]
        struct TaggedHunk {
            branch: Branch,
            before_start: u32,
            before_end: u32,
            after_start: u32,
            after_end: u32,
        }

        let mut all_hunks = Vec::new();

        for hunk in diff_a.hunks() {
            all_hunks.push(TaggedHunk {
                branch: Branch::A,
                before_start: hunk.before.start,
                before_end: hunk.before.end,
                after_start: hunk.after.start,
                after_end: hunk.after.end,
            });
        }

        for hunk in diff_b.hunks() {
            all_hunks.push(TaggedHunk {
                branch: Branch::B,
                before_start: hunk.before.start,
                before_end: hunk.before.end,
                after_start: hunk.after.start,
                after_end: hunk.after.end,
            });
        }

        // Sort hunks by their position in the common base
        all_hunks.sort_by(|a, b| {
            a.before_start
                .cmp(&b.before_start)
                .then(a.before_end.cmp(&b.before_end))
        });

        let get_text = |tokens: &[Token], interner: &Interner<&str>| -> String {
            let mut result = String::new();
            for &token in tokens {
                result.push_str(interner[token]);
            }
            result
        };

        let mut merged = String::new();
        let mut conflicts = Vec::new();
        let mut pos = 0u32;

        let mut i = 0;
        while i < all_hunks.len() {
            let hunk = &all_hunks[i];

            let unchanged = &input_a.before[pos as usize..hunk.before_start as usize];
            for &token in unchanged {
                merged.push_str(input_a.interner[token]);
            }

            let has_conflict = i + 1 < all_hunks.len() && {
                let next = &all_hunks[i + 1];
                next.before_start < hunk.before_end // overlap in the base
            };

            if has_conflict {
                let hunk1 = &all_hunks[i];
                let hunk2 = &all_hunks[i + 1];

                let (a_hunk, b_hunk) = match (&hunk1.branch, &hunk2.branch) {
                    (Branch::A, Branch::B) => (hunk1, hunk2),
                    (Branch::B, Branch::A) => (hunk2, hunk1),
                    _ => unreachable!("imara_diff guarantees monotonic hunks per branch"),
                };

                let a_tokens =
                    &input_a.after[a_hunk.after_start as usize..a_hunk.after_end as usize];
                let a_content = get_text(a_tokens, &input_a.interner);

                let b_tokens =
                    &input_b.after[b_hunk.after_start as usize..b_hunk.after_end as usize];
                let b_content = get_text(b_tokens, &input_b.interner);

                let info = ConflictInfo {
                    base_line: hunk.before_start,
                    a_content,
                    b_content,
                };
                merged.push_str(&info.marker_string(&self.marker_a, &self.marker_b));
                conflicts.push(info);

                pos = hunk1.before_end.max(hunk2.before_end);
                i += 2; // advance past both hunks
                continue;
            }
            let (tokens, interner) = match hunk.branch {
                Branch::A => (
                    &input_a.after[hunk.after_start as usize..hunk.after_end as usize],
                    &input_a.interner,
                ),
                Branch::B => (
                    &input_b.after[hunk.after_start as usize..hunk.after_end as usize],
                    &input_b.interner,
                ),
            };

            for &token in tokens {
                merged.push_str(interner[token]);
            }

            pos = hunk.before_end;
            i += 1;
        }

        // Add remaining unchanged tokens from common base
        let remaining_tokens = &input_a.before[pos as usize..];
        for &token in remaining_tokens {
            merged.push_str(input_a.interner[token]);
        }

        MergeResult::new(merged, conflicts)
    }
}

#[derive(Debug, Clone)]
pub struct MergeResult {
    pub merged: String,
    pub conflicts: Vec<ConflictInfo>,
    pub has_conflicts: bool,
}

impl MergeResult {
    fn new(merged: String, conflicts: Vec<ConflictInfo>) -> Self {
        let has_conflicts = !conflicts.is_empty();
        Self {
            merged,
            conflicts,
            has_conflicts,
        }
    }
}
