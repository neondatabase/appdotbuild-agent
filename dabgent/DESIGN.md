# Dabgent - System Design Document

## 1. Executive Summary

Dabgent is a modular AI agent orchestration system built in Rust that enables autonomous task execution through Large Language Models (LLMs). The system provides a robust framework for planning, executing, and monitoring AI-driven workflows with tool integration, sandboxed execution, and real-time user interaction.

### Key Features
- Multi-LLM provider support (Anthropic, Gemini)
- Sandboxed tool execution environment
- Event-driven architecture with async processing
- Terminal-based user interface
- Extensible tool system
- Task planning and validation

## 2. System Architecture

### 2.1 High-Level Architecture

![System Architecture](docs/images/architecture.png)

<details>
<summary>View Mermaid Source</summary>

```mermaid
graph TB
    subgraph "User Interface Layer"
        CLI[dabgent_cli<br/>Terminal UI]
        API[dabgent_fastapi<br/>REST API]
    end

    subgraph "Core Agent Layer"
        AGENT[dabgent_agent]
        PIPELINE[Pipeline System]
        PROCESSOR[Event Processor]
        LLM[LLM Integration]
    end

    subgraph "Service Layer"
        MQ[dabgent_mq<br/>Message Queue]
        SANDBOX[dabgent_sandbox<br/>Dagger Integration]
    end

    subgraph "Infrastructure"
        TOKIO[Tokio Runtime]
        DB[(PostgreSQL)]
        FS[File System]
    end

    CLI --> AGENT
    API --> AGENT
    AGENT --> PIPELINE
    PIPELINE --> PROCESSOR
    PROCESSOR --> LLM
    AGENT --> MQ
    AGENT --> SANDBOX
    MQ --> DB
    SANDBOX --> FS

    style AGENT fill:#f9f,stroke:#333,stroke-width:4px
    style CLI fill:#bbf,stroke:#333,stroke-width:2px
    style SANDBOX fill:#fbf,stroke:#333,stroke-width:2px
```
</details>

### 2.2 Component Overview

| Component | Responsibility | Key Interfaces | Internal Modules |
|-----------|---------------|----------------|------------------|
| **dabgent_agent** | Core agent logic, LLM integration, task execution | `Processor`, `Pipeline`, `Completion` | `event.rs`, `llm.rs`, `processor.rs` |
| **dabgent_cli** | Terminal UI, user interaction, command parsing | `App`, `Agent`, `Session` | `main.rs`, `app.rs`, `ui.rs`, `widgets.rs`, `events.rs` |
| **dabgent_mq** | Message queue for inter-component communication | `Publisher`, `Subscriber` | `models.rs`, database integration |
| **dabgent_sandbox** | Isolated execution environment for tools | `Sandbox`, `DaggerClient` | `dagger.rs`, container orchestration |
| **dabgent_fastapi** | REST API endpoints for external integration | `Toolset`, `Validator` | `toolset.rs`, `validator.rs` |

### 2.3 Dependency Graph

![Dependency Graph](docs/images/dependencies.png)

<details>
<summary>View Mermaid Source</summary>

```mermaid
graph LR
    CLI[dabgent_cli] --> AGENT[dabgent_agent]
    AGENT --> MQ[dabgent_mq]
    AGENT --> SANDBOX[dabgent_sandbox]

    AGENT --> RIG[rig-core]
    AGENT --> TOKIO[tokio]
    MQ --> SQLX[sqlx]
    SANDBOX --> DAGGER[dagger-sdk]
    CLI --> RATATUI[ratatui]

    style AGENT fill:#f9f,stroke:#333,stroke-width:4px
    style CLI fill:#bbf,stroke:#333,stroke-width:2px
```
</details>

## 3. Core Components Design

### 3.0 Module-Level Architecture (Graph Analysis)

#### Function Call Hierarchy

![Call Hierarchy](docs/images/call-hierarchy.png)

<details>
<summary>View Mermaid Source</summary>

```mermaid
graph TD
    subgraph "Entry Points"
        MAIN[main<br/>dabgent_cli]
        MQ_MAIN[main<br/>dabgent_mq]
        SANDBOX_MAIN[main<br/>dabgent_sandbox]
    end

    subgraph "CLI Layer"
        APP_NEW[App::new]
        APP_RUN[App::run]
        HANDLE_EVENTS[handle_key_events]
        RUN_PIPELINE[agent::run_pipeline]
    end

    subgraph "Agent Core"
        PIPELINE_NEW[Pipeline::new]
        PROCESSOR_RUN[Processor::run]
        COMPLETION_NEW[Completion::new]
        EVENT_TYPE[Event::event_type]
    end

    MAIN --> APP_NEW
    MAIN --> RUN_PIPELINE
    APP_RUN --> HANDLE_EVENTS
    RUN_PIPELINE --> PIPELINE_NEW
    PIPELINE_NEW --> PROCESSOR_RUN
    PROCESSOR_RUN --> COMPLETION_NEW
```
</details>

## 3. Core Components Design

### 3.1 Agent Module (`dabgent_agent/src/agent.rs`)

#### 3.1.1 Worker Component

```rust
pub struct Worker<S, T> {
    llm: Box<dyn CompletionModel>,
    model: String,
    tools: Vec<T>,
    sandbox: Arc<S>,
    store: Arc<Store>,
    subscriber: Subscriber,
}

impl Worker {
    pub async fn run(&self, thread_id: Uuid, retry: bool) -> Result<()> {
        // 1. Load thread events
        // 2. Fold events into thread state
        // 3. Generate LLM completion
        // 4. Process response
        // 5. Emit events
    }
}
```

**Responsibilities:**
- Manage LLM completions
- Maintain conversation context
- Process thread events
- Emit completion events

#### 3.1.2 ToolWorker Component

```rust
pub struct ToolWorker<S, T> {
    tools: Vec<T>,
    sandbox: Arc<S>,
    store: Arc<Store>,
    subscriber: Subscriber,
}

impl ToolWorker {
    pub async fn run(&self, thread_id: Uuid, retry: bool) -> Result<()> {
        // 1. Check for pending tool calls
        // 2. Execute tools in sandbox
        // 3. Collect artifacts
        // 4. Emit tool response events
    }
}
```

**Responsibilities:**
- Execute tool calls
- Manage sandbox environment
- Collect and emit artifacts
- Handle tool failures

### 3.2 Pipeline System (`dabgent_agent/src/pipeline.rs`)

#### 3.2.1 Pipeline Architecture

```rust
pub struct Pipeline<S, T> {
    llm: Box<dyn CompletionModel>,
    model: String,
    preamble: String,
    tools: Vec<T>,
    sandbox: Arc<S>,
    store: Arc<Store>,
}

pub struct PipelineBuilder<S, T> {
    llm: Option<Box<dyn CompletionModel>>,
    model: Option<String>,
    preamble: Option<String>,
    tools: Vec<T>,
    sandbox: Option<Arc<S>>,
    store: Option<Arc<Store>>,
}
```

**Pipeline Execution Flow:**
1. Initialize workers (Worker + ToolWorker)
2. Subscribe to thread events
3. Process messages in loop
4. Coordinate worker execution
5. Handle completion conditions

### 3.3 Planning Module (`dabgent_agent/src/planning.rs`)

```rust
pub struct PlanningAgent {
    id: String,
    workers: Vec<Worker>,
    validators: Vec<Box<dyn Validator>>,
}

impl PlanningAgent {
    pub async fn process_message(&self, message: Message) -> Result<Plan> {
        // 1. Analyze message intent
        // 2. Generate execution plan
        // 3. Validate plan
        // 4. Setup worker coordination
    }
}
```

**Planning Features:**
- Task decomposition
- Dependency analysis
- Resource allocation
- Progress monitoring
- Validation checks

### 3.4 LLM Integration (`dabgent_agent/src/llm.rs`)

```rust
pub struct Completion {
    preamble: Option<String>,
    history: Vec<Message>,
    tools: Vec<ToolDefinition>,
    max_tokens: Option<u32>,
    temperature: Option<f32>,
    additional_params: HashMap<String, Value>,
}

pub trait CompletionModel {
    async fn completion(&self, request: CompletionRequest) -> Result<CompletionResponse>;
}
```

**Supported Providers:**
- Anthropic Claude
- Google Gemini
- Extensible for additional providers

### 3.5 Thread Management (`dabgent_agent/src/thread.rs`)

```rust
pub struct Thread {
    id: Uuid,
    events: Vec<Event>,
    state: ThreadState,
    done: bool,
}

impl Thread {
    pub fn fold(events: Vec<Event>) -> Self {
        // Reconstruct thread state from events
    }

    pub fn process(&mut self, event: Event) -> Result<()> {
        // Update thread state with new event
    }
}
```

**Event Types:**
- UserMessage
- AssistantMessage
- ToolCall
- ToolResponse
- SystemMessage

### 3.6 Toolbox System (`dabgent_agent/src/toolbox/`)

#### 3.6.1 Tool Interface

```rust
pub trait Tool: Send + Sync {
    fn name(&self) -> String;
    fn definition(&self) -> ToolDefinition;
    async fn call(&self, args: Value, sandbox: &dyn Sandbox) -> Result<ToolResponse>;
}
```

#### 3.6.2 Available Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| **ReadFile** | Read file contents | `path: String` |
| **WriteFile** | Write content to file | `path: String, content: String` |
| **EditFile** | Modify existing file | `path: String, changes: Vec<Edit>` |
| **RmFile** | Delete file | `path: String` |
| **LsDir** | List directory contents | `path: String` |
| **Bash** | Execute shell commands | `command: String` |
| **TaskListTool** | Manage task lists | `tasks: Vec<Task>` |
| **DoneTool** | Mark completion | `message: String` |

## 4. Data Flow and Sequences

### 4.1 Main Execution Flow

![Sequence Flow](docs/images/sequence-flow.png)

<details>
<summary>View Mermaid Source</summary>

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant Agent
    participant Pipeline
    participant Processor
    participant LLM
    participant Sandbox
    participant MQ

    User->>CLI: Input request
    CLI->>CLI: Parse arguments
    CLI->>CLI: Initialize UI (ratatui)
    CLI->>Agent: Create pipeline
    Agent->>Pipeline: Initialize with LLM + tools
    Agent->>MQ: Setup message queue

    loop Event Processing
        Pipeline->>Processor: Run processor
        Processor->>LLM: Request completion
        LLM-->>Processor: Response + tool calls
        Processor->>Sandbox: Execute tools (Dagger)
        Sandbox-->>Processor: Tool results
        Processor->>MQ: Queue events
        MQ-->>Pipeline: Event updates
    end

    Pipeline-->>Agent: Completion
    Agent-->>CLI: Final response
    CLI-->>User: Display output
```
</details>

### 4.2 Event Processing Flow

![Event State Machine](docs/images/event-state.png)

<details>
<summary>View Mermaid Source</summary>

```mermaid
stateDiagram-v2
    [*] --> UserMessage: User input
    UserMessage --> Processing: Agent receives
    Processing --> LLMCompletion: Generate response
    LLMCompletion --> ToolCalls: Has tool calls
    LLMCompletion --> AssistantMessage: No tools needed
    ToolCalls --> SandboxExecution: Execute in Dagger
    SandboxExecution --> ToolResponses: Collect results
    ToolResponses --> Processing: Continue
    AssistantMessage --> Done: Task complete
    Done --> [*]
```
</details>

### 4.3 Inter-Module Communication

```mermaid
graph LR
    subgraph "Function Calls Discovered"
        CLI_MAIN["CLI::main()<br/>Calls: Args::parse, App::new, agent::run_pipeline"]
        AGENT_PIPELINE["Pipeline::new()<br/>Calls: Processor::run"]
        PROCESSOR["Processor::run()<br/>Calls: Completion::new, LLM providers"]
    end

    CLI_MAIN --> AGENT_PIPELINE
    AGENT_PIPELINE --> PROCESSOR
```

## 5. API Specifications

### 5.1 CLI Interface

```bash
# Main command structure
dabgent [OPTIONS] <COMMAND>

Commands:
  run       Execute agent with input
  plan      Generate execution plan
  validate  Validate configuration

Options:
  --model <MODEL>     LLM model to use
  --provider <PROVIDER>  LLM provider (anthropic, gemini)
  --sandbox <TYPE>   Sandbox type (local, docker)
  --verbose          Enable detailed logging
```

### 5.2 Pipeline Builder API

```rust
let pipeline = PipelineBuilder::new()
    .llm(Box::new(AnthropicClient::new(api_key)))
    .model("claude-3-opus")
    .preamble("You are a helpful assistant")
    .tool(ReadFile::new())
    .tool(WriteFile::new())
    .tool(Bash::new())
    .sandbox(Arc::new(LocalSandbox::new()))
    .store(Arc::new(Store::new(db_url)))
    .build()?;

pipeline.run(thread_id).await?;
```

### 5.3 Tool Definition Schema

```json
{
  "name": "read_file",
  "description": "Read contents of a file",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Path to the file"
      }
    },
    "required": ["path"]
  }
}
```

## 6. Database Schema

### 6.1 Core Tables

```sql
-- Threads table
CREATE TABLE threads (
    id UUID PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    status VARCHAR(50) NOT NULL,
    metadata JSONB
);

-- Events table
CREATE TABLE events (
    id UUID PRIMARY KEY,
    thread_id UUID REFERENCES threads(id),
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL,
    INDEX idx_thread_events (thread_id, created_at)
);

-- Artifacts table
CREATE TABLE artifacts (
    id UUID PRIMARY KEY,
    thread_id UUID REFERENCES threads(id),
    file_path TEXT NOT NULL,
    content TEXT,
    created_at TIMESTAMP NOT NULL
);
```

## 7. Configuration

### 7.1 Environment Variables

```bash
# LLM Configuration
ANTHROPIC_API_KEY=your_key
GEMINI_API_KEY=your_key
DEFAULT_MODEL=claude-3-opus

# Database
DATABASE_URL=postgresql://user:pass@localhost/dabgent

# Sandbox
SANDBOX_TYPE=local
SANDBOX_TIMEOUT=30

# Logging
RUST_LOG=dabgent=debug
```

### 7.2 Configuration File (`dabgent.toml`)

```toml
[llm]
default_provider = "anthropic"
default_model = "claude-3-opus"
max_tokens = 4096
temperature = 0.7

[pipeline]
max_iterations = 10
timeout_seconds = 300

[sandbox]
type = "local"
work_dir = "/tmp/dabgent"
max_file_size = 10485760  # 10MB

[tools]
enabled = ["read_file", "write_file", "bash", "task_list"]
```

## 8. Error Handling

### 8.1 Error Types

```rust
#[derive(Error, Debug)]
pub enum DabgentError {
    #[error("LLM error: {0}")]
    LLM(String),

    #[error("Tool execution error: {0}")]
    ToolExecution(String),

    #[error("Sandbox error: {0}")]
    Sandbox(String),

    #[error("Pipeline error: {0}")]
    Pipeline(String),

    #[error("Validation error: {0}")]
    Validation(String),
}
```

### 8.2 Error Recovery Strategies

1. **Retry Logic**: Automatic retry for transient failures
2. **Graceful Degradation**: Fallback to simpler operations
3. **Error Context**: Rich error messages with context
4. **Rollback**: Undo partial changes on failure

## 9. Security Considerations

### 9.1 Sandbox Isolation

- File system isolation
- Network restrictions
- Resource limits (CPU, memory, disk)
- Process isolation
- No access to host system

### 9.2 Input Validation

- Sanitize user inputs
- Validate tool parameters
- Path traversal prevention
- Command injection prevention

### 9.3 API Security

- API key management
- Rate limiting
- Request validation
- Secure storage of credentials

## 10. Performance Characteristics

### 10.1 Concurrency Model

- **Async Runtime**: Tokio-based async execution
- **Message Queue**: SQLx-backed persistent queue
- **Parallel Tool Execution**: Sandboxed parallel tool runs
- **Event-Driven**: Non-blocking event processing

### 10.2 Scalability Considerations

| Component | Scalability Factor | Bottleneck |
|-----------|-------------------|------------|
| dabgent_cli | Single-user TUI | Terminal I/O |
| dabgent_agent | Multi-threaded | LLM API rate limits |
| dabgent_mq | Database-backed | PostgreSQL capacity |
| dabgent_sandbox | Container-based | Docker daemon |
| dabgent_fastapi | Async handlers | Network I/O |

## 11. Testing Strategy

### 11.1 Test Types

| Type | Coverage | Tools |
|------|----------|-------|
| Unit Tests | 80% | cargo test |
| Integration Tests | 60% | custom harness |
| E2E Tests | 40% | scenario tests |
| Performance Tests | Critical paths | criterion |

### 11.2 Mock Infrastructure

```rust
pub struct MockSandbox {
    files: HashMap<String, String>,
    commands: Vec<String>,
}

pub struct MockLLM {
    responses: Vec<CompletionResponse>,
}

pub struct MockTaskList {
    tasks: Vec<Task>,
    updates: Vec<Update>,
}
```

## 12. Deployment

### 12.1 Docker Deployment

```dockerfile
FROM rust:1.75 as builder
WORKDIR /app
COPY . .
RUN cargo build --release

FROM debian:bookworm-slim
COPY --from=builder /app/target/release/dabgent /usr/local/bin/
CMD ["dabgent"]
```


### 13.2 Logging

```rust
use tracing::{info, debug, error};

info!("Pipeline started", thread_id = %thread_id);
debug!("Executing tool", tool = %tool_name);
error!("Tool execution failed", error = %err);
```

### 13.3 Tracing

- Distributed tracing with OpenTelemetry
- Request correlation IDs
- Performance profiling


## 15. Conclusion

Dabgent provides a robust, extensible framework for AI agent orchestration with strong emphasis on:
- **Modularity**: Clear separation of concerns
- **Safety**: Sandboxed execution environment
- **Flexibility**: Multiple LLM providers and tools
- **Reliability**: Error handling and recovery
- **Performance**: Async processing and optimization
- **Usability**: Clean APIs and documentation

The architecture supports both current requirements and future growth through its modular design and well-defined interfaces.