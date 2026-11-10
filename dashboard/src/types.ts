export type Mode = "demo" | "model";

export interface Config {
  mode: Mode;
  model: string | null;
}

export interface Task {
  name: string;
  issue: string;
  language: string;
  runnable: boolean;
}

export interface ModelEvent {
  type: "model";
  step: number;
  t: number;
  text: string;
}

export interface ToolEvent {
  type: "tool";
  step: number;
  t: number;
  name: string;
  arguments: Record<string, unknown>;
  result: string;
}

export type AgentEvent = ModelEvent | ToolEvent;

export interface RunResult {
  success: boolean;
  status: string;
  steps: number;
  tool_calls: number;
  stop_reason: string;
  summary: string;
  patch?: string;
  test_output?: string;
}

export type RunStatus = "running" | "done" | "error";

export interface Run {
  id: string;
  task: string;
  issue: string;
  language: string;
  mode: Mode;
  model: string | null;
  status: RunStatus;
  started_at: number;
  seconds: number;
  events?: AgentEvent[];
  result: RunResult | null;
  error: string | null;
}
