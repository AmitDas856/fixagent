import type { Config, Run, Task } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("Can't reach the fixagent server. Check that it is running.");
  }
  const text = await response.text();
  let data: unknown = null;
  try {
    data = JSON.parse(text);
  } catch {
    // Not JSON, for example a proxy error page.
  }
  if (!response.ok) {
    const message =
      data !== null && typeof data === "object" && "error" in data
        ? String((data as { error: unknown }).error)
        : `The server replied with status ${response.status}.`;
    throw new Error(message);
  }
  return data as T;
}

export function getConfig(): Promise<Config> {
  return request<Config>("/api/config");
}

export function getTasks(): Promise<Task[]> {
  return request<Task[]>("/api/tasks");
}

export function getRuns(): Promise<Run[]> {
  return request<Run[]>("/api/runs");
}

export function getRun(id: string): Promise<Run> {
  return request<Run>(`/api/runs/${encodeURIComponent(id)}`);
}

export function startRun(task: string): Promise<Run> {
  return request<Run>("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }),
  });
}
