import { useCallback, useEffect, useMemo, useState } from "react";

import { getConfig, getRun, getRuns, getTasks, startRun } from "./api";
import RunView from "./components/RunView";
import TaskList from "./components/TaskList";
import type { Config, Run, Task } from "./types";

const POLL_MS = 600;

/** The newest run for each task, keyed by task name. */
function latestByTask(runs: Run[]): Record<string, Run> {
  const latest: Record<string, Run> = {};
  for (const run of runs) {
    const current = latest[run.task];
    if (!current || run.started_at > current.started_at) {
      latest[run.task] = run;
    }
  }
  return latest;
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);

  const latest = useMemo(() => latestByTask(runs), [runs]);
  const selectedTask = tasks.find((task) => task.name === selected) ?? null;
  const selectedRunId = selected ? (latest[selected]?.id ?? null) : null;
  const anyRunning = runs.some((run) => run.status === "running");

  const fail = useCallback((reason: unknown) => {
    setError(reason instanceof Error ? reason.message : String(reason));
  }, []);

  // First load: settings, the list of bugs, and any runs already on the server.
  useEffect(() => {
    Promise.all([getConfig(), getTasks(), getRuns()])
      .then(([loadedConfig, loadedTasks, loadedRuns]) => {
        setConfig(loadedConfig);
        setTasks(loadedTasks);
        setRuns(loadedRuns);
        setSelected((current) => current ?? loadedTasks[0]?.name ?? null);
      })
      .catch(fail);
  }, [fail]);

  // While anything is running, keep the list of runs fresh.
  useEffect(() => {
    if (!anyRunning) return;
    const timer = window.setInterval(() => {
      getRuns().then(setRuns).catch(fail);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [anyRunning, fail]);

  // Load the selected run's steps, and keep loading them until it finishes.
  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const load = () => {
      getRun(selectedRunId)
        .then((run) => {
          if (cancelled) return;
          setDetail(run);
          if (run.status === "running") {
            timer = window.setTimeout(load, POLL_MS);
          }
        })
        .catch((reason) => {
          if (!cancelled) fail(reason);
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [selectedRunId, fail]);

  const run = useCallback(
    async (taskNames: string[]) => {
      setError(null);
      try {
        const started = await Promise.all(taskNames.map((name) => startRun(name)));
        setRuns((current) => [...started, ...current]);
      } catch (reason) {
        fail(reason);
      }
    },
    [fail],
  );

  const finished = tasks.filter((task) => latest[task.name]?.status === "done");
  const fixed = finished.filter((task) => latest[task.name]?.result?.success);
  const runnable = tasks.filter((task) => task.runnable).map((task) => task.name);

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>fixagent</h1>
          <p className="masthead-sub">An agent that repairs bugs and proves it with the tests.</p>
        </div>
        <div className="masthead-meta">
          {config && (
            <p className={`mode mode-${config.mode}`}>
              {config.mode === "demo"
                ? "Demo mode: replaying a scripted model, not a real one"
                : `Model: ${config.model}`}
            </p>
          )}
          <p className="tally" aria-live="polite">
            {finished.length === 0
              ? "No bugs run yet"
              : `${fixed.length} of ${finished.length} bugs fixed`}
          </p>
        </div>
      </header>

      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      <main className="bench">
        <TaskList
          tasks={tasks}
          latest={latest}
          selected={selected}
          busy={anyRunning}
          onSelect={setSelected}
          onRun={(name) => run([name])}
          onRunAll={() => run(runnable)}
        />
        <RunView task={selectedTask} run={detail && detail.task === selected ? detail : null} />
      </main>
    </div>
  );
}
