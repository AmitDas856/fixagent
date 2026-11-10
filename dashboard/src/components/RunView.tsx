import type { Run, Task } from "../types";
import PatchView from "./PatchView";
import StepTimeline from "./StepTimeline";
import { languageName } from "./TaskList";

interface Props {
  task: Task | null;
  run: Run | null;
}

function Verdict({ run }: { run: Run }) {
  if (run.status === "error") {
    return (
      <div className="verdict verdict-fail">
        <p className="verdict-stamp">Error</p>
        <p className="verdict-text">{run.error}</p>
      </div>
    );
  }
  const result = run.result;
  if (!result) return null;
  const fixed = result.success;
  return (
    <div className={fixed ? "verdict verdict-pass" : "verdict verdict-fail"}>
      <p className="verdict-stamp">{fixed ? "Fixed" : "Not fixed"}</p>
      <div className="verdict-text">
        <p>
          {fixed
            ? "The tests failed before the agent ran and pass now."
            : result.status === "not fixed"
              ? `The tests still fail. The agent stopped because: ${result.stop_reason}.`
              : `Nothing to fix: ${result.status}.`}
        </p>
        {result.summary && <p className="verdict-summary">Agent's note: {result.summary}</p>}
        <p className="verdict-meta">
          {result.tool_calls} tool calls in {run.seconds.toFixed(1)} seconds
          {run.mode === "demo" ? ", scripted model" : run.model ? `, ${run.model}` : ""}
        </p>
      </div>
    </div>
  );
}

export default function RunView({ task, run }: Props) {
  if (!task) {
    return (
      <section className="run">
        <p className="empty">Pick a bug on the left to see the agent work on it.</p>
      </section>
    );
  }

  return (
    <section className="run" aria-label={`Run for ${task.name}`}>
      <div className="ticket">
        <p className="ticket-name">
          {task.name} <span className="language">{languageName(task.language)}</span>
        </p>
        <p className="ticket-issue">{task.issue}</p>
      </div>

      {!run ? (
        <p className="empty">This bug has not been run yet. Press Run to start the agent.</p>
      ) : (
        <>
          <h2>Steps</h2>
          <StepTimeline events={run.events ?? []} running={run.status === "running"} />
          <Verdict run={run} />
          {run.result?.patch && (
            <>
              <h2>Patch</h2>
              <PatchView patch={run.result.patch} />
            </>
          )}
        </>
      )}
    </section>
  );
}
