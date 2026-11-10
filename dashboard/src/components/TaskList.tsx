import type { Run, Task } from "../types";

const LANGUAGE_NAMES: Record<string, string> = {
  python: "Python",
  cpp: "C++",
  rust: "Rust",
  hack: "Hack",
};

export function languageName(language: string): string {
  return LANGUAGE_NAMES[language] ?? language;
}

/** A short state word for a task, from its newest run. */
export function taskState(run: Run | undefined): { label: string; tone: string } {
  if (!run) return { label: "Not run", tone: "idle" };
  if (run.status === "running") return { label: "Running", tone: "running" };
  if (run.status === "error") return { label: "Error", tone: "fail" };
  return run.result?.success
    ? { label: "Fixed", tone: "pass" }
    : { label: "Not fixed", tone: "fail" };
}

interface Props {
  tasks: Task[];
  latest: Record<string, Run>;
  selected: string | null;
  busy: boolean;
  onSelect: (name: string) => void;
  onRun: (name: string) => void;
  onRunAll: () => void;
}

export default function TaskList({
  tasks,
  latest,
  selected,
  busy,
  onSelect,
  onRun,
  onRunAll,
}: Props) {
  const anyRunnable = tasks.some((task) => task.runnable);

  return (
    <aside className="tasks" aria-label="Bugs">
      <div className="tasks-head">
        <h2>Bugs</h2>
        <button
          type="button"
          className="button"
          onClick={onRunAll}
          disabled={busy || !anyRunnable}
        >
          Run all
        </button>
      </div>

      {tasks.length === 0 ? (
        <p className="empty">No bugs loaded. Start the server with a tasks file.</p>
      ) : (
        <ul className="task-list">
          {tasks.map((task) => {
            const run = latest[task.name];
            const state = taskState(run);
            const running = run?.status === "running";
            return (
              <li key={task.name} className={task.name === selected ? "task is-selected" : "task"}>
                <button
                  type="button"
                  className="task-main"
                  onClick={() => onSelect(task.name)}
                  aria-current={task.name === selected}
                >
                  <span className="task-name">{task.name}</span>
                  <span className="task-issue">{task.issue}</span>
                  <span className="task-foot">
                    <span className="language">{languageName(task.language)}</span>
                    <span className={`state state-${state.tone}`}>{state.label}</span>
                  </span>
                </button>
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => {
                    onSelect(task.name);
                    onRun(task.name);
                  }}
                  disabled={running || !task.runnable}
                  title={task.runnable ? undefined : "This bug needs a real model to run"}
                >
                  {running ? "Running" : run ? "Run again" : "Run"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
