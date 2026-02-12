use std::fmt;

#[derive(Debug, Clone)]
pub enum State {
    /// entry point
    Init { prompt: String },
    /// Claude decomposes prompt into tasks.md with checkboxes
    Plan { prompt: String },
    /// Claude works on unchecked tasks, checking them off
    Work,
    /// run configured validation steps (build, test, etc.)
    Validate { step_idx: usize },
    /// Claude reviews the final diff
    Review,
    /// generate patch output
    Export,
    /// terminal: success
    Done,
    /// terminal: failure
    Failed { reason: String },
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
            State::Plan { .. } => write!(f, "Plan"),
            State::Work => write!(f, "Work"),
            State::Validate { step_idx } => write!(f, "Validate(step={step_idx})"),
            State::Review => write!(f, "Review"),
            State::Export => write!(f, "Export"),
            State::Done => write!(f, "Done"),
            State::Failed { reason } => write!(f, "Failed({reason})"),
        }
    }
}
