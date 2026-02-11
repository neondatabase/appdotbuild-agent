use std::collections::HashMap;
use std::fmt;

#[derive(Debug, Clone)]
pub enum Phase {
    Tests,
    Code,
}

impl fmt::Display for Phase {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Phase::Tests => write!(f, "Tests"),
            Phase::Code => write!(f, "Code"),
        }
    }
}

#[derive(Debug, Clone)]
pub enum State {
    Init {
        prompt: String,
    },
    RewriteTask {
        prompt: String,
    },
    LoadTaskList {
        task_list: String,
    },
    WriteTests {
        task_list: String,
    },
    WriteCode {
        task_list: String,
        context: Option<String>,
    },
    Validate {
        phase: Phase,
        step_idx: usize,
    },
    Review,
    Export,
    Done,
    Failed {
        reason: String,
    },
}

impl State {
    pub fn is_terminal(&self) -> bool {
        matches!(self, State::Done | State::Failed { .. })
    }
}

impl fmt::Display for State {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            State::Init { .. } => write!(f, "Init"),
            State::RewriteTask { .. } => write!(f, "RewriteTask"),
            State::LoadTaskList { .. } => write!(f, "LoadTaskList"),
            State::WriteTests { .. } => write!(f, "WriteTests"),
            State::WriteCode { context, .. } => {
                if context.is_some() {
                    write!(f, "WriteCode(retry)")
                } else {
                    write!(f, "WriteCode")
                }
            }
            State::Validate { phase, step_idx } => {
                write!(f, "Validate({}, step={})", phase, step_idx)
            }
            State::Review => write!(f, "Review"),
            State::Export => write!(f, "Export"),
            State::Done => write!(f, "Done"),
            State::Failed { reason } => write!(f, "Failed({})", reason),
        }
    }
}

/// tracks retry counts per backtrack edge
pub struct RetryTracker {
    counts: HashMap<&'static str, usize>,
    max_retries: usize,
}

impl RetryTracker {
    pub fn new(max_retries: usize) -> Self {
        Self {
            counts: HashMap::new(),
            max_retries,
        }
    }

    /// returns true if retry is allowed, false if max exceeded.
    /// increments the counter on each call.
    pub fn try_retry(&mut self, edge: &'static str) -> bool {
        let count = self.counts.entry(edge).or_insert(0);
        *count += 1;
        *count <= self.max_retries
    }

    pub fn count(&self, edge: &'static str) -> usize {
        self.counts.get(edge).copied().unwrap_or(0)
    }
}
