import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  Download,
  FileText,
  Layers3,
  LockKeyhole,
  MessageCircleQuestion,
  Send,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  UserRound
} from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

import {
  askProjectExplainer,
  generatedProjectDownloadUrl,
  getJob,
  getProjectGuide,
  type JobState,
  type ProjectGuideResponse
} from "../lib/api";

interface ProjectGuidePageProps {
  jobId: string;
  onBack: () => void;
}

const suggestedQuestions = [
  "What frontend experience was built?",
  "How is this project structured?",
  "Which technologies does it use?",
  "How does the main user journey work?"
];

export function ProjectGuidePage({ jobId, onBack }: ProjectGuidePageProps) {
  const [job, setJob] = useState<JobState | null>(null);
  const [response, setResponse] = useState<ProjectGuideResponse | null>(null);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);

  const explanation = response?.explanation;
  const messages = explanation?.messages ?? [];
  const remainingPrompts = explanation?.remaining_prompts ?? 10;
  const promptLimit = explanation?.prompt_limit ?? 10;
  const quotaUsed = Math.max(promptLimit - remainingPrompts, 0);
  const limitReached = remainingPrompts <= 0;

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setBusy(true);
      setError(null);
      try {
        const [nextJob, nextGuide] = await Promise.all([getJob(jobId), getProjectGuide(jobId)]);
        if (!cancelled) {
          setJob(nextJob);
          setResponse(nextGuide);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unable to load the project explainer.");
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  const projectFacts = useMemo(() => {
    const folder = job?.artifacts.find((artifact) => artifact.kind === "folder");
    const fileCount = Number(folder?.metadata.file_count ?? 0);
    const passedChecks = job?.validation_results.filter((item) => item.passed).length ?? 0;
    return [
      { label: "Release", value: job?.release_status ?? "loading" },
      { label: "Stack", value: job?.project_spec.capability_id ?? "detected" },
      { label: "Files", value: fileCount ? String(fileCount) : "—" },
      { label: "Checks", value: passedChecks ? `${passedChecks} passed` : "—" }
    ];
  }, [job]);

  async function submitQuestion(candidate?: string) {
    const nextQuestion = (candidate ?? question).trim();
    if (!nextQuestion || busy || limitReached) return;
    setBusy(true);
    setError(null);
    setQuestion("");
    try {
      setResponse(await askProjectExplainer(jobId, nextQuestion));
    } catch (caught) {
      setQuestion(nextQuestion);
      setError(caught instanceof Error ? caught.message : "The project explainer could not answer.");
    } finally {
      setBusy(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitQuestion();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitQuestion();
    }
  }

  return (
    <div className="project-guide-shell project-chat-shell">
      <div className="guide-ambient guide-ambient-one" />
      <div className="guide-ambient guide-ambient-two" />
      <header className="project-guide-topbar">
        <button type="button" onClick={onBack}>
          <ArrowLeft size={15} aria-hidden="true" />
          Back to Studio
        </button>
        <div className="project-guide-brand">
          <span><TerminalSquare size={17} aria-hidden="true" /></span>
          <strong>AGENTIC::FORGE</strong>
          <em>PROJECT EXPLAINER</em>
        </div>
        {job?.artifacts.some((artifact) => artifact.kind === "zip") ? (
          <a href={generatedProjectDownloadUrl(jobId)}>
            <Download size={14} aria-hidden="true" />
            Download project
          </a>
        ) : <span />}
      </header>

      <main className="project-guide-main project-chat-main">
        <section className="guide-project-hero project-chat-hero">
          <div className="guide-project-heading">
            <p><Sparkles size={13} aria-hidden="true" /> Ask about this verified build</p>
            <h1>{job?.request.project_id ?? "Loading project…"}</h1>
            <span>{job?.request.prompt ?? "Reading the verified project evidence."}</span>
          </div>
          <div className="guide-project-ribbon project-chat-ribbon">
            {projectFacts.map((fact) => (
              <div key={fact.label}>
                <span>{fact.label}</span>
                <strong>{fact.value}</strong>
              </div>
            ))}
          </div>
        </section>

        <div className="project-chat-layout">
          <aside className="project-chat-rail">
            <section className="project-chat-policy">
              <span><LockKeyhole size={14} /> Read-only</span>
              <h2>Explanation, not generation.</h2>
              <p>
                This assistant can explain the verified project. It cannot reveal, create,
                rewrite, repair, or modify source code.
              </p>
            </section>

            <section className="project-chat-quota" aria-label="Question allowance">
              <div>
                <span>Questions available</span>
                <strong>{remainingPrompts}<small>/{promptLimit}</small></strong>
              </div>
              <div className="project-chat-quota-track">
                <i style={{ width: `${Math.min((quotaUsed / promptLimit) * 100, 100)}%` }} />
              </div>
              <p>Every submitted prompt counts. Repeated answers are served from cache.</p>
            </section>

            <section className="project-chat-capabilities">
              <h3><CheckCircle2 size={14} /> This assistant can</h3>
              <p><Layers3 size={13} /> Explain architecture and technologies</p>
              <p><FileText size={13} /> Point to relevant project files</p>
              <p><ShieldCheck size={13} /> Describe validation and known risks</p>
            </section>

            <section className="project-chat-model">
              <span>Focused model</span>
              <strong>{explanation?.model ?? "gpt-6-luna"}</strong>
              <small>One model · verified evidence · no write access</small>
            </section>
          </aside>

          <section className="project-chat-window" aria-live="polite">
            <header>
              <div>
                <span className="project-chat-presence"><i /></span>
                <div>
                  <strong>Project Explainer</strong>
                  <small>Grounded in the generated software</small>
                </div>
              </div>
              <span><LockKeyhole size={12} /> Read-only session</span>
            </header>

            <div className="project-chat-transcript">
              {!messages.length && !busy ? (
                <div className="project-chat-welcome">
                  <span><Bot size={24} /></span>
                  <p>PROJECT CONTEXT READY</p>
                  <h2>What would you like to understand?</h2>
                  <small>
                    Ask about the architecture, technology choices, user journeys, APIs,
                    validation, or how an existing feature works.
                  </small>
                  <div>
                    {suggestedQuestions.map((suggestion) => (
                      <button
                        type="button"
                        key={suggestion}
                        onClick={() => void submitQuestion(suggestion)}
                      >
                        <MessageCircleQuestion size={14} />
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {messages.map((message) => (
                <article
                  className="project-chat-message"
                  data-role={message.role}
                  data-refusal={message.refusal || undefined}
                  key={message.message_id}
                >
                  <span>{message.role === "assistant" ? <Bot size={15} /> : <UserRound size={15} />}</span>
                  <div>
                    <header>
                      <strong>{message.role === "assistant" ? "Project Explainer" : "You"}</strong>
                      {message.cached ? <em>cached · no model cost</em> : null}
                      {message.refusal ? <em>read-only boundary</em> : null}
                    </header>
                    <p>{message.content}</p>
                    {message.citations.length ? (
                      <footer>
                        {message.citations.map((citation) => (
                          <code key={citation}><FileText size={11} /> {citation}</code>
                        ))}
                      </footer>
                    ) : null}
                  </div>
                </article>
              ))}

              {busy ? (
                <article className="project-chat-message" data-role="assistant">
                  <span><Bot size={15} /></span>
                  <div className="project-chat-thinking">
                    <strong>Reading verified project evidence</strong>
                    <span><i /><i /><i /></span>
                  </div>
                </article>
              ) : null}
              <div ref={conversationEndRef} />
            </div>

            <form className="project-chat-composer" onSubmit={handleSubmit}>
              {error ? <div className="project-chat-error">{error}</div> : null}
              {limitReached ? (
                <div className="project-chat-limit">
                  <LockKeyhole size={15} />
                  This project has used all 10 explanation prompts.
                </div>
              ) : (
                <div>
                  <textarea
                    aria-label="Ask about this project"
                    disabled={busy}
                    maxLength={2000}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={handleComposerKeyDown}
                    placeholder="Ask how an existing part of this project works…"
                    rows={3}
                    value={question}
                  />
                  <button type="submit" disabled={busy || !question.trim()} aria-label="Send question">
                    <Send size={15} />
                  </button>
                </div>
              )}
              <p>
                <LockKeyhole size={11} /> Explanations only. Code generation and project changes are blocked.
                <span>{remainingPrompts} prompts remaining</span>
              </p>
            </form>
          </section>
        </div>
      </main>
    </div>
  );
}
