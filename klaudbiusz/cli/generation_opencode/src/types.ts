export interface GenerationMetrics {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  turns: number;
  generation_time_sec?: number;
  app_dir?: string | null;
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
}

export interface BuilderOptions {
  appName: string;
  outputDir: string;
  model?: string;
  provider?: string;
  port?: number;
  verbose?: boolean;
}
