export interface GenerationMetrics {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  turns: number;
  generation_time_sec?: number;
  app_dir?: string | null;
}

export interface McpServerConfig {
  type: "local";
  command: string[];
  env?: Record<string, string>;
  enabled: boolean;
}

export interface ProviderOptions {
  apiKey?: string;
  baseURL?: string;
  timeout?: number;
}

export interface OpencodeConfig {
  $schema?: string;
  model?: string;
  provider?: Record<string, { options: ProviderOptions }>;
  mcp?: Record<string, McpServerConfig>;
}

export interface BuilderOptions {
  appName: string;
  outputDir: string;
  mcpBinary: string;
  mcpArgs: string[];
  model?: string;
  provider?: string;
  port?: number;
  verbose?: boolean;
}
