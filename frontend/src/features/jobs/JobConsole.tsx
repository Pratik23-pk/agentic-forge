import {
  AlertTriangle,
  Braces,
  Database,
  Monitor,
  RefreshCw,
  Send,
  Server,
  ShieldCheck
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

import { StatusBadge } from "../../components/StatusBadge";
import type { JobState, WorkerKind } from "../../lib/api";
import { createReadableProjectName } from "../../lib/projectName";

const workerIcons = {
  database: Database,
  backend: Server,
  frontend: Monitor
};

interface JobConsoleProps {
  jobs: JobState[];
  selectedJob: JobState | null;
  busy: boolean;
  error: string | null;
  onSubmit: (prompt: string, projectId: string, runImmediately: boolean) => Promise<void>;
  onRefresh: () => Promise<void>;
  onRunNext: () => Promise<void>;
  onSelect: (job: JobState) => void;
}

export function JobConsole({
  jobs,
  selectedJob,
  busy,
  error,
  onSubmit,
  onRefresh,
  onRunNext,
  onSelect
}: JobConsoleProps) {
  const [prompt, setPrompt] = useState("");
  const [projectId, setProjectId] = useState(createReadableProjectName);
  const [runImmediately, setRunImmediately] = useState(true);

  const selectedOutput = useMemo(() => {
    if (!selectedJob) {
      return "";
    }
    return selectedJob.worker_results.map((result) => result.output).join("\n\n");
  }, [selectedJob]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!prompt.trim()) {
      return;
    }
    await onSubmit(prompt, projectId, runImmediately);
    setPrompt("");
  }

  return (
    <main className="console-grid">
      <section className="submit-panel" aria-label="Submit job">
        <form onSubmit={handleSubmit}>
          <div className="field-row">
            <label htmlFor="project-id">Project name</label>
            <input
              id="project-id"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              placeholder="India Gaming Showcase"
            />
          </div>
          <label htmlFor="job-prompt">Request</label>
          <textarea
            id="job-prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Build a backend route, database migration, or frontend dashboard change..."
            rows={7}
          />
          <div className="button-row">
            <button type="submit" disabled={busy || !prompt.trim()} title="Submit job">
              <Send size={16} aria-hidden="true" />
              {runImmediately ? "Submit + Run" : "Queue"}
            </button>
            <button type="button" className="secondary" onClick={onRefresh} disabled={busy} title="Refresh jobs">
              <RefreshCw size={16} aria-hidden="true" />
              Refresh
            </button>
            <button type="button" className="secondary" onClick={onRunNext} disabled={busy} title="Run next queued job">
              <RefreshCw size={16} aria-hidden="true" />
              Run Next
            </button>
          </div>
          <label className="toggle-row" htmlFor="run-immediately">
            <input
              id="run-immediately"
              type="checkbox"
              checked={runImmediately}
              onChange={(event) => setRunImmediately(event.target.checked)}
            />
            Run immediately
          </label>
          {error ? (
            <div className="error-banner" role="alert">
              <AlertTriangle size={16} aria-hidden="true" />
              {error}
            </div>
          ) : null}
        </form>
      </section>

      <section className="job-list" aria-label="Job history">
        <div className="section-heading">
          <Braces size={18} aria-hidden="true" />
          <h2>Jobs</h2>
        </div>
        <div className="job-stack">
          {jobs.length === 0 ? <p className="empty">No jobs yet.</p> : null}
          {jobs.map((job) => (
            <button
              className={`job-row ${selectedJob?.job_id === job.job_id ? "active" : ""}`}
              key={job.job_id}
              type="button"
              onClick={() => onSelect(job)}
            >
              <span className="job-title">{job.request.prompt}</span>
              <StatusBadge status={job.status} />
            </button>
          ))}
        </div>
      </section>

      <section className="detail-panel" aria-label="Job detail">
        {selectedJob ? (
          <>
            <header className="detail-header">
              <div>
                <p>{selectedJob.job_id}</p>
                <h2>{selectedJob.request.project_id}</h2>
              </div>
              <StatusBadge status={selectedJob.status} />
            </header>

            <div className="detail-block">
              <h3>Tasks</h3>
              <div className="task-grid">
                {selectedJob.tasks.map((task) => {
                  const Icon = workerIcons[task.worker_kind as WorkerKind];
                  return (
                    <article className="task-item" key={task.task_id}>
                      <div>
                        <Icon size={18} aria-hidden="true" />
                        <strong>{task.title}</strong>
                      </div>
                      <StatusBadge status={task.status} />
                      <span>Attempt {task.attempt} of {task.max_attempts}</span>
                    </article>
                  );
                })}
              </div>
            </div>

            <div className="detail-block">
              <h3>Guardrails</h3>
              <div className="guardrail-list">
                {selectedJob.guardrail_reports.map((report, index) => (
                  <div className="guardrail-row" key={`${report.name}-${index}`}>
                    <ShieldCheck size={16} aria-hidden="true" />
                    <span>{report.name}</span>
                    <StatusBadge status={report.passed ? "succeeded" : "blocked"} />
                  </div>
                ))}
              </div>
            </div>

            <div className="detail-block">
              <h3>Route</h3>
              <pre>{JSON.stringify(selectedJob.route ?? selectedJob.evaluation, null, 2)}</pre>
            </div>

            <div className="detail-block">
              <h3>Tool Calls</h3>
              <pre>
                {JSON.stringify(
                  selectedJob.worker_results.flatMap((result) => result.tool_calls ?? []),
                  null,
                  2
                )}
              </pre>
            </div>

            <div className="detail-block">
              <h3>Output</h3>
              <pre>{selectedOutput || "No worker output yet."}</pre>
            </div>
          </>
        ) : (
          <p className="empty">Select a job to inspect execution state.</p>
        )}
      </section>
    </main>
  );
}
