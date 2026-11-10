import type { AgentEvent, ToolEvent } from "../types";

const TOOL_LABELS: Record<string, string> = {
  list_files: "List files",
  read_file: "Read file",
  search_code: "Search code",
  edit_file: "Edit file",
  write_file: "Write file",
  run_tests: "Run tests",
  run_command: "Run command",
  finish: "Finish",
};

/** The one argument worth showing next to the tool name. */
function target(event: ToolEvent): string {
  const args = event.arguments;
  for (const key of ["path", "pattern", "command"]) {
    const value = args[key];
    if (typeof value === "string" && value) return value;
  }
  return "";
}

function outcome(event: ToolEvent): { label: string; tone: string } | null {
  if (event.result.startsWith("ERROR")) return { label: "Rejected", tone: "fail" };
  if (event.name === "run_tests") {
    return event.result.startsWith("Tests PASSED")
      ? { label: "Tests pass", tone: "pass" }
      : { label: "Tests fail", tone: "fail" };
  }
  return null;
}

interface Props {
  events: AgentEvent[];
  running: boolean;
}

export default function StepTimeline({ events, running }: Props) {
  const toolEvents = events.filter((event): event is ToolEvent => event.type === "tool");

  if (toolEvents.length === 0) {
    return <p className="empty">{running ? "Starting the agent" : "The agent took no steps."}</p>;
  }

  return (
    <ol className="steps">
      {toolEvents.map((event, index) => {
        const result = outcome(event);
        const detail = target(event);
        return (
          <li key={index} className="step">
            <details>
              <summary>
                <span className="step-tool">{TOOL_LABELS[event.name] ?? event.name}</span>
                {detail && <code className="step-target">{detail}</code>}
                {result && <span className={`state state-${result.tone}`}>{result.label}</span>}
                <span className="step-time">{event.t.toFixed(1)}s</span>
              </summary>
              <pre className="step-output">{event.result}</pre>
            </details>
          </li>
        );
      })}
      {running && (
        <li className="step step-pending" aria-live="polite">
          Working on the next step
        </li>
      )}
    </ol>
  );
}
