// TypeSpec definition for the Agent Server API.
// This file specifies the data types, interfaces, and operations for the API.
// It serves as the source of truth for the API structure, implemented by
// `models.py` (Python Pydantic models) and `async_server.py` (FastAPI server).
// Refer to `architecture.puml` for its place in the overall system.

import "@typespec/http";
import "@typespec/rest";

using TypeSpec.Http;
using TypeSpec.Rest;

@service({
  title: "Neon Agent Server API",
  version: "1.1.0",
})

namespace AgentServerApi;

// --- Enums ---

@doc("Defines the current status of the agent.") 
enum AgentStatus {
  @doc("Agent is actively processing the request, it is free to reject new requests in this state.")
  running,

  @doc("Agent has completed its current task or requires user feedback, current state can be requested with no overhead.")
  idle,
}

@doc("Defines the type of message being sent by the agent to the user.")
enum MessageKind {
  @doc("An intermediate result/update while the agent is still running. The platform should not typically query API during this state unless restoring after a failure.")
  StageResult,

  @doc("The agent has paused and requires feedback or additional information from the user.")
  RefinementRequest,

  @doc("The agent encountered an error it couldn't recover from. Retrying likely requires user intervention or infrastructure changes.")
  RuntimeError,

  @doc("The final successful result indicating the application generation is complete and ready for review.")
  ReviewResult,

  @doc("Empty event sent periodically to keep the connection alive during long periods of inactivity.")
  KeepAlive,
}

// --- Diff summary ---

@doc("A lightweight summary entry describing modifications to a single file in the current step.")
model DiffStatEntry {
  @doc("Path of the file that changed (relative to the project root).")
  path: string;

  @doc("Number of lines inserted in this file during the current step.")
  insertions: int32;

  @doc("Number of lines deleted in this file during the current step.")
  deletions: int32;
}

// --- Models ---

@doc("Represents a single file with its path and content.")
model FileEntry {
  @doc("The relative path of the file.")
  path: string;

  @doc("The content of the file.")
  content: string;
}

@doc("Represents a single content block in an external message.")
model ExternalContentBlock {
  @doc("Deprecated. The role of the block. Will be removed in the future.")
  role: 'assistant';

  @doc("The content of the block.")
  content: string;

  // @doc("The timestamp of the block.")
  // timestamp: utcDateTime;
}

@doc("Represents a message from the agent to the user, including structured content blocks, state, and any code changes.")
model AgentMessage {
  @doc("Fixed field for client to detect agent message in the history") 
  role: 'assistant';

  @doc("The type of message being sent.")
  kind: MessageKind;

  @doc("Deprecated field for content. Use 'messages' field instead for structured messaging.")
  content?: string;

  @doc("Structured content blocks. Present only for new clients.")
  messages?: ExternalContentBlock[];

  @doc("Updated state of the Agent Server that should be presented in the next request to continue the conversation.")
  agentState: Record<string, unknown> | null;

  @doc("A unified diff format string representing code changes made by the agent.")
  unifiedDiff: string | null;

  @doc("Hash (e.g., SHA-256) of the complete unified diff for the current application state.")
  completeDiffHash: string | null;

  @doc("Lightweight per-file summary of changes since the previous message.")
  diffStat: DiffStatEntry[] | null;
  
  @doc("Generated application name suitable for use as a GitHub repository name.")
  app_name: string | null;
  
  @doc("Generated commit message suitable for use in Git commits.")
  commit_message: string | null;
}

@doc("Structure of the data payload within each Server-Sent Event (SSE).")
model AgentSseEvent {
  @doc("Current status of the agent (running or idle).")
  status: AgentStatus;

  @doc("The trace ID corresponding to the POST request.")
  @encodedName("application/json", "traceId")
  traceId?: string;

  @doc("The detailed message payload from the agent.")
  message: AgentMessage;
}

@doc("Represents a message from the user to the agent.")
model UserMessage {
  @doc("Fixed field for client to detect user message in the history") 
  role: 'user'

  @doc("The content of the user's message.")
  content: string;
}

@doc("Represents a conversation message that can be either from the user or the agent.")
union ConversationMessage {
  UserMessage,
  AgentMessage,
}

@doc("Request body for initiating or continuing interaction with the Agent Server.")
model AgentRequest {
  @doc("History of all messages in the current conversation thread.")
  allMessages: ConversationMessage[];

  @doc("All files in the workspace to be used for diff generation.")
  allFiles?: FileEntry[];

  @doc("Unique identifier for the application instance.")
  applicationId: string;

  @doc("Unique identifier for this request/response cycle.")
  traceId: string;

  @doc("Unique identifier of the template the agent supports.")
  templateId?: string;

  @doc("The full state of the Agent Server to restore from.")
  agentState?: Record<string, unknown> | null;

  @doc("Settings for the agent execution, such as maximum number of iterations.")
  settings?: Record<string, unknown>;
}

@doc("Error response model.")
model ErrorResponse {
  @doc("Error message.")
  error: string;
  
  @doc("Additional error details.")
  details?: string;
}

// --- Operations ---

@doc("Main endpoint for sending user messages and receiving agent responses via Server-Sent Events.")
@route("/message")
interface MessageOperations {
  @post
  @summary("Send a message to the agent and stream responses.")
  @doc("""
  Send a message to the agent and stream responses via SSE.

  Platform (Backend) -> Agent Server API Spec:
  POST Request:
  - allMessages: [str] - history of all user messages
  - applicationId: str - required for Agent Server for tracing
  - traceId: str - required - a string used in SSE events
  - templateId: str - optional an ID of the template to use in the agent
  - agentState: {..} or null - the full state of the Agent to restore from
  - settings: {...} - json with settings with number of iterations etc

  SSE Response:
  - status: "running" | "idle" - defines if the Agent stopped or continues running
  - traceId: corresponding traceId of the input
  - message: {kind, content, agentState, unifiedDiff} - response from the Agent Server
  """)
  sendMessage(
    @body body: AgentRequest
  ): OkResponse<string> | BadRequestResponse | InternalServerErrorResponse;
}

@doc("Health check endpoint.")
@route("/health")
interface HealthOperations {
  @get
  @summary("Dagger connection health check endpoint")
  healthCheck(): OkResponse<{
    status: string;
    dagger_connection: string;
    alpine_version: string;
  }>;
}

@doc("Standard Bad Request response.")
model BadRequestResponse {
  @statusCode _: 400;
  @body body: {
    error: string;
  };
}

@doc("Standard Internal Server Error response.")
model InternalServerErrorResponse {
  @statusCode _: 500;
  @body body: ErrorResponse;
} 