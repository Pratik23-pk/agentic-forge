import {
  ArrowRight,
  BookOpenCheck,
  Check,
  ChevronRight,
  CircleDot,
  Code2,
  Database,
  Download,
  ExternalLink,
  FileCode2,
  Film,
  Github,
  Image as ImageIcon,
  Layers3,
  MessageSquare,
  Mic,
  Monitor,
  Paperclip,
  Play,
  RefreshCw,
  Save,
  ShieldCheck,
  Sparkles,
  Square,
  TerminalSquare,
  X
} from "lucide-react";
import { FormEvent, type MouseEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  generatedProjectDownloadUrl,
  collaborationWebSocketUrl,
  createSupabaseProject,
  deleteUploadedMedia,
  getGeneratedFileContent,
  getJob,
  getMetrics,
  getPreview,
  getPreviewLogs,
  listGeneratedFiles,
  listDesignTokens,
  listJobs,
  listProviderStatus,
  previewScreenshotUrl,
  runNextJob,
  startPreview,
  stopPreview,
  submitHumanFeedback,
  submitJob,
  syncToGitHub,
  transcribeVoice,
  updateGeneratedFile,
  updateDesignTokens,
  uploadMedia,
  type DesignTokenFile,
  type GeneratedFile,
  type GenerationProfile,
  type HumanFeedbackDecision,
  type HumanFeedbackRequest,
  type JobState,
  type Metrics,
  type PreviewRecord,
  type ProviderStatus,
  type TaskStatus,
  type UploadedMediaAsset,
  type WorkerKind
} from "../lib/api";
import { createReadableProjectName } from "../lib/projectName";
import { LandingPage } from "./LandingPage";
import { ProjectGuidePage } from "./ProjectGuidePage";

type NodeStatus = "queued" | "active" | "review" | "complete" | "failed" | "blocked";
type WorkspaceView = "preview" | "files" | "activity" | "controls";

interface StudioNode {
  id: string;
  order: string;
  title: string;
  role: string;
  description: string;
  stack: string;
  status: NodeStatus;
  progress: number;
  workerKind?: WorkerKind;
}

const defaultPrompt =
  "Build a SaaS analytics dashboard with role-based access, Stripe billing and a FastAPI backend.";

const templates = [
  "Realtime workspace",
  "AI support platform",
  "Developer portal"
];

const certifiedStacks = [
  ["", "Auto-detect stack"],
  ["nextjs-fullstack", "Next.js full-stack"],
  ["react-fastapi", "React + FastAPI"],
  ["react-node", "React + Node/Express"],
  ["fastapi-api", "FastAPI API"],
  ["node-api", "Node/Express API"],
  ["react-vite", "React/Vite frontend"],
  ["python-cli", "Python CLI"]
] as const;

const pipelineCards = [
  {
    order: "01",
    title: "Architect Agent",
    body: "Turns intent into requirements, system boundaries, data contracts and a build plan."
  },
  {
    order: "02",
    title: "Interface Agent",
    body: "Creates responsive product UI, reusable components and stateful user flows."
  },
  {
    order: "03",
    title: "Backend Agent",
    body: "Implements APIs, domain logic, authentication, queues and service integrations."
  },
  {
    order: "04",
    title: "Data Agent",
    body: "Designs schemas, migrations, indexing, caching and retrieval pipelines."
  },
  {
    order: "05",
    title: "QA + Security Agent",
    body: "Runs tests, threat checks, dependency validation and regression analysis."
  },
  {
    order: "06",
    title: "Artifact Writer",
    body: "Preserves the latest files, verifies archive parity and labels each release for preview, download or publication."
  }
];

const controlItems = [
  "Human approval gates",
  "Staged validation workspace",
  "Structured planner decisions",
  "Job-level audit trail"
];

export function App() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const handlePopState = () => setPath(window.location.pathname);
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  function enterStudio(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    window.history.pushState({}, "", "/studio");
    setPath("/studio");
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  function navigate(pathname: string) {
    window.history.pushState({}, "", pathname);
    setPath(pathname);
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  const guideMatch = path.match(/^\/studio\/projects\/([^/]+)\/guide$/);
  if (guideMatch) {
    return (
      <ProjectGuidePage
        jobId={decodeURIComponent(guideMatch[1])}
        onBack={() => navigate("/studio")}
      />
    );
  }

  return path.startsWith("/studio") ? (
    <DevelopmentPanel
      onOpenGuide={(jobId) => navigate(`/studio/projects/${encodeURIComponent(jobId)}/guide`)}
    />
  ) : (
    <LandingPage onEnterStudio={enterStudio} />
  );
}

function DevelopmentPanel({ onOpenGuide }: { onOpenGuide: (jobId: string) => void }) {
  const [jobs, setJobs] = useState<JobState[]>([]);
  const [selectedJob, setSelectedJob] = useState<JobState | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [prompt, setPrompt] = useState("");
  const [projectId, setProjectId] = useState(createReadableProjectName);
  const [runImmediately, setRunImmediately] = useState(true);
  const [capabilityId, setCapabilityId] = useState("");
  const [generationProfile, setGenerationProfile] = useState<GenerationProfile>("auto");
  const [uploadedAssets, setUploadedAssets] = useState<UploadedMediaAsset[]>([]);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [transcribing, setTranscribing] = useState(false);
  const [transcriptionCost, setTranscriptionCost] = useState(0);
  const [activeNodeId, setActiveNodeId] = useState("backend");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generatedFiles, setGeneratedFiles] = useState<GeneratedFile[]>([]);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [filePreview, setFilePreview] = useState("");
  const [fileSha256, setFileSha256] = useState("");
  const [fileDirty, setFileDirty] = useState(false);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [previewRecord, setPreviewRecord] = useState<PreviewRecord | null>(null);
  const [previewLogs, setPreviewLogs] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [collaboratorCount, setCollaboratorCount] = useState(0);
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("preview");
  const automaticPreviewJobs = useRef(new Set<string>());
  const mediaInputRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const recordingStartedAtRef = useRef(0);
  const cancelRecordingRef = useRef(false);

  const nodes = useMemo(() => buildNodes(selectedJob), [selectedJob]);
  const activeNode = nodes.find((node) => node.id === activeNodeId) ?? nodes[2];
  const selectedOutput = selectedJob?.worker_results.map((result) => result.output).join("\n\n");
  const selectedToolCalls = selectedJob?.worker_results.flatMap((result) => result.tool_calls ?? []) ?? [];
  const activeFeedback = activeFeedbackRequest(selectedJob);

  async function refresh() {
    const [nextJobs, nextMetrics] = await Promise.all([listJobs(), getMetrics()]);
    setJobs(nextJobs);
    setMetrics(nextMetrics);
    if (selectedJob) {
      setSelectedJob(nextJobs.find((job) => job.job_id === selectedJob.job_id) ?? selectedJob);
    }
  }

  async function loadGeneratedOutput(job: JobState | null) {
    setGeneratedFiles([]);
    setSelectedFilePath(null);
    setFilePreview("");
    setFileSha256("");
    setFileDirty(false);
    setArtifactError(null);

    if (!job?.artifacts?.some((artifact) => artifact.kind === "folder")) {
      return;
    }

    try {
      const listing = await listGeneratedFiles(job.job_id);
      setGeneratedFiles(listing.files);
      const firstPreviewable = listing.files.find((file) => isPreviewable(file.path)) ?? listing.files[0];
      if (firstPreviewable) {
        await handleSelectGeneratedFile(job.job_id, firstPreviewable.path);
      }
    } catch (err) {
      setArtifactError(err instanceof Error ? err.message : "Unable to load generated files.");
    }
  }

  async function handleSelectGeneratedFile(jobId: string, path: string) {
    setSelectedFilePath(path);
    setArtifactError(null);
    if (!isPreviewable(path)) {
      setFilePreview("Binary or generated asset selected. Download the ZIP to inspect it locally.");
      return;
    }
    try {
      const content = await getGeneratedFileContent(jobId, path);
      setFilePreview(content);
      setFileSha256(await sha256(content));
      setFileDirty(false);
    } catch (err) {
      setArtifactError(err instanceof Error ? err.message : "Unable to preview generated file.");
    }
  }

  async function handleSaveGeneratedFile() {
    if (!selectedJob || !selectedFilePath || !fileDirty) {
      return;
    }
    setBusy(true);
    setArtifactError(null);
    try {
      const result = await updateGeneratedFile(
        selectedJob.job_id,
        selectedFilePath,
        filePreview,
        fileSha256
      );
      setFileSha256(result.sha256);
      setFileDirty(false);
      const listing = await listGeneratedFiles(selectedJob.job_id);
      setGeneratedFiles(listing.files);
    } catch (err) {
      setArtifactError(err instanceof Error ? err.message : "Unable to save generated file.");
    } finally {
      setBusy(false);
    }
  }

  async function handleStartPreview() {
    if (!selectedJob) {
      return;
    }
    setPreviewBusy(true);
    setArtifactError(null);
    try {
      const record = await startPreview(selectedJob.job_id);
      setPreviewRecord(record);
      setPreviewLogs("");
    } catch (err) {
      setArtifactError(err instanceof Error ? err.message : "Unable to start preview.");
    } finally {
      setPreviewBusy(false);
    }
  }

  async function handleStopPreview() {
    if (!selectedJob) {
      return;
    }
    setPreviewBusy(true);
    try {
      setPreviewRecord(await stopPreview(selectedJob.job_id));
    } catch (err) {
      setArtifactError(err instanceof Error ? err.message : "Unable to stop preview.");
    } finally {
      setPreviewBusy(false);
    }
  }

  async function handleLoadPreviewLogs() {
    if (!selectedJob) {
      return;
    }
    try {
      setPreviewLogs(await getPreviewLogs(selectedJob.job_id));
    } catch (err) {
      setArtifactError(err instanceof Error ? err.message : "Unable to load preview logs.");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!prompt.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const job = await submitJob(
        prompt,
        projectId || "default",
        runImmediately,
        capabilityId || undefined,
        generationProfile,
        uploadedAssets.map((asset) => asset.asset_id)
      );
      setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
      setSelectedJob(job);
      setActiveNodeId(firstActiveNode(buildNodes(job)).id);
      setMetrics(await getMetrics());
      setUploadedAssets([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workflow launch failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleMediaSelection(files: FileList | null) {
    if (!files?.length) {
      return;
    }
    setUploadBusy(true);
    setError(null);
    try {
      const assets = await uploadMedia(Array.from(files));
      setUploadedAssets((current) => [...current, ...assets]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Media upload failed.");
    } finally {
      setUploadBusy(false);
    }
  }

  async function handleRemoveMedia(assetId: string) {
    try {
      await deleteUploadedMedia(assetId);
      setUploadedAssets((current) => current.filter((asset) => asset.asset_id !== assetId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to remove uploaded media.");
    }
  }

  async function startVoiceRecording() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Voice recording is not supported by this browser.");
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = preferredRecordingMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recordingStreamRef.current = stream;
      recordingChunksRef.current = [];
      cancelRecordingRef.current = false;
      recordingStartedAtRef.current = Date.now();
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          recordingChunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const cancelled = cancelRecordingRef.current;
        const duration = Math.max((Date.now() - recordingStartedAtRef.current) / 1000, 0.1);
        const blob = new Blob(recordingChunksRef.current, {
          type: recorder.mimeType || "audio/webm"
        });
        recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
        recordingStreamRef.current = null;
        recorderRef.current = null;
        recordingChunksRef.current = [];
        setRecording(false);
        setRecordingSeconds(0);
        if (!cancelled) {
          void transcribeRecording(blob, duration);
        }
      };
      recorder.start(500);
      setRecording(true);
    } catch (err) {
      recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
      setError(err instanceof Error ? err.message : "Microphone access failed.");
    }
  }

  function stopVoiceRecording(cancelled = false) {
    cancelRecordingRef.current = cancelled;
    if (recorderRef.current?.state !== "inactive") {
      recorderRef.current?.stop();
    }
  }

  async function transcribeRecording(blob: Blob, duration: number) {
    setTranscribing(true);
    setError(null);
    try {
      const result = await transcribeVoice(blob, duration);
      setPrompt((current) => [current.trim(), result.transcript].filter(Boolean).join(" "));
      setTranscriptionCost((current) => current + result.estimated_cost_usd);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice transcription failed.");
    } finally {
      setTranscribing(false);
    }
  }

  function selectGenerationProfile(profile: GenerationProfile) {
    setGenerationProfile(profile);
  }

  async function handleNewProject() {
    await Promise.allSettled(
      uploadedAssets.map((asset) => deleteUploadedMedia(asset.asset_id))
    );
    if (recording) {
      stopVoiceRecording(true);
    }
    setUploadedAssets([]);
    setSelectedJob(null);
    setPrompt("");
    setProjectId(createReadableProjectName());
    setGenerationProfile("auto");
    setTranscriptionCost(0);
    setWorkspaceView("preview");
    setError(null);
  }

  async function handleRunNext() {
    setBusy(true);
    setError(null);
    try {
      const result = await runNextJob();
      if ("status" in result && result.status === "idle") {
        setError("No queued workflow is waiting.");
      } else {
        const job = result as JobState;
        setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
        setSelectedJob(job);
        setActiveNodeId(firstActiveNode(buildNodes(job)).id);
      }
      setMetrics(await getMetrics());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Queued workflow failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRefresh() {
    setBusy(true);
    setError(null);
    try {
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleHumanFeedback(decision: HumanFeedbackDecision) {
    if (!selectedJob || !activeFeedback) {
      return;
    }
    if (decision === "request_changes" && !feedbackMessage.trim()) {
      setError("Add a short note describing what should change.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const job = await submitHumanFeedback(
        selectedJob.job_id,
        decision,
        feedbackMessage.trim() || undefined,
        activeFeedback.checkpoint_id
      );
      setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
      setSelectedJob(job);
      setActiveNodeId(firstActiveNode(buildNodes(job)).id);
      setFeedbackMessage("");
      setMetrics(await getMetrics());
    } catch (err) {
      try {
        const current = await getJob(selectedJob.job_id);
        setSelectedJob(current);
        setJobs((jobs) => [current, ...jobs.filter((item) => item.job_id !== current.job_id)]);
      } catch {
      }
      setError(err instanceof Error ? err.message : "Feedback submission failed.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh().catch((err) => {
      setError(err instanceof Error ? err.message : "Initial load failed.");
    });
  }, []);

  useEffect(() => {
    if (!recording) {
      return;
    }
    const timer = window.setInterval(() => {
      setRecordingSeconds(Math.max(0, Math.floor((Date.now() - recordingStartedAtRef.current) / 1000)));
    }, 250);
    return () => window.clearInterval(timer);
  }, [recording]);

  useEffect(() => {
    const jobId = selectedJob?.job_id;
    const isActive =
      selectedJob &&
      ["running", "evaluating", "retrying", "awaiting_human_feedback"].includes(
        selectedJob.status
      );
    if (!jobId || !isActive) {
      return;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        const job = await getJob(jobId);
        if (cancelled) {
          return;
        }
        setSelectedJob(job);
        setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
        if (
          !["running", "evaluating", "retrying", "awaiting_human_feedback"].includes(
            job.status
          )
        ) {
          setMetrics(await getMetrics());
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Workflow status polling failed.");
        }
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), 1800);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedJob?.job_id, selectedJob?.status]);

  useEffect(() => {
    void loadGeneratedOutput(selectedJob);
  }, [selectedJob?.job_id, selectedJob?.artifacts?.length]);

  useEffect(() => {
    setPreviewRecord(null);
    setPreviewLogs("");
    const jobId = selectedJob?.job_id;
    if (!jobId || !selectedJob.artifacts.some((artifact) => artifact.kind === "folder")) {
      return;
    }
    void getPreview(jobId).then(setPreviewRecord).catch(async () => {
      const releaseReview = activeFeedbackRequest(selectedJob)?.gate === "release";
      const previewReady =
        ["succeeded", "failed", "blocked"].includes(selectedJob.status) || releaseReview;
      if (!previewReady || automaticPreviewJobs.current.has(jobId)) {
        return;
      }
      automaticPreviewJobs.current.add(jobId);
      setPreviewBusy(true);
      try {
        setPreviewRecord(await startPreview(jobId));
        setWorkspaceView("preview");
      } catch (err) {
        setArtifactError(err instanceof Error ? err.message : "Automatic sandbox preview failed.");
      } finally {
        setPreviewBusy(false);
      }
    });
  }, [selectedJob?.job_id, selectedJob?.artifacts?.length, selectedJob?.status]);

  useEffect(() => {
    const jobId = selectedJob?.job_id;
    if (!jobId || !selectedJob.artifacts.some((artifact) => artifact.kind === "folder")) {
      setCollaboratorCount(0);
      return;
    }
    const socket = new WebSocket(collaborationWebSocketUrl(jobId));
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as Record<string, unknown>;
        if (message.type === "presence" && typeof message.collaborators === "number") {
          setCollaboratorCount(message.collaborators);
        }
        if (
          message.type === "file_updated" &&
          message.path === selectedFilePath &&
          selectedFilePath !== null &&
          !fileDirty
        ) {
          void handleSelectGeneratedFile(jobId, selectedFilePath);
        }
      } catch {
        return;
      }
    };
    return () => socket.close();
  }, [selectedJob?.job_id, selectedJob?.artifacts?.length, selectedFilePath, fileDirty]);

  return (
    <div className="studio-shell-v2">
      <header className="studio-topbar-v2">
        <a className="studio-brand-v2" href="/" aria-label="Return to Agentic Forge home">
          <span className="brand-mark">
            <TerminalSquare size={18} aria-hidden="true" />
          </span>
          <span>
            <strong>AGENTIC::FORGE</strong>
            <em>SOFTWARE BUILDER</em>
          </span>
        </a>

        <div className="studio-project-status">
          <span className="studio-status-dot" data-status={selectedJob?.status ?? "ready"} />
          <div>
            <strong>{selectedJob?.request.project_id ?? (projectId || "New project")}</strong>
            <span>{selectedJob ? selectedJob.status.replace(/_/g, " ") : "Ready to build"}</span>
          </div>
        </div>

        <div className="studio-top-actions">
          {metrics ? (
            <span className="studio-metric">
              {metrics.jobs_succeeded}/{metrics.jobs_submitted} successful
            </span>
          ) : null}
          <button type="button" onClick={handleRefresh} disabled={busy}>
            <RefreshCw size={15} aria-hidden="true" />
            Refresh
          </button>
          {selectedJob?.status === "succeeded" && selectedJob.release_status === "verified" ? (
            <button
              className="studio-guide-button"
              type="button"
              onClick={() => onOpenGuide(selectedJob.job_id)}
            >
              <BookOpenCheck size={15} aria-hidden="true" />
              Project guide
            </button>
          ) : null}
          <button type="button" onClick={() => setWorkspaceView("controls")}>
            <ShieldCheck size={15} aria-hidden="true" />
            Release
          </button>
        </div>
      </header>

      <main className="studio-workspace-v2">
        <aside className="studio-chat-panel" aria-label="Agent conversation">
          <header className="studio-chat-header">
            <div>
              <p>Build conversation</p>
              <h1>{selectedJob ? selectedJob.request.project_id : "What will you build?"}</h1>
            </div>
            <button
              type="button"
              onClick={() => void handleNewProject()}
            >
              <Sparkles size={14} aria-hidden="true" />
              New
            </button>
          </header>

          {jobs.length > 0 ? (
            <div className="studio-history-strip" aria-label="Recent projects">
              {jobs.slice(0, 5).map((job) => (
                <button
                  className={selectedJob?.job_id === job.job_id ? "selected" : ""}
                  key={job.job_id}
                  type="button"
                  onClick={() => {
                    setSelectedJob(job);
                    setProjectId(job.request.project_id);
                    setActiveNodeId(firstActiveNode(buildNodes(job)).id);
                  }}
                >
                  <span data-status={job.status} />
                  {job.request.project_id}
                </button>
              ))}
            </div>
          ) : null}

          <div className="studio-chat-stream">
            <BuildConversation job={selectedJob} nodes={nodes} />
            <HumanCheckpointPanel
              busy={busy}
              feedback={activeFeedback}
              message={feedbackMessage}
              onChangeMessage={setFeedbackMessage}
              onSubmit={handleHumanFeedback}
            />
            {error ? (
              <div className="studio-error-v2" role="alert">
                <CircleDot size={14} aria-hidden="true" />
                {error}
              </div>
            ) : null}
          </div>

          <form className="studio-composer" onSubmit={handleSubmit}>
            <div className="studio-project-name-field">
              <label htmlFor="project-name">Project name</label>
              <input
                id="project-name"
                maxLength={80}
                required
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                placeholder="India Gaming Showcase"
              />
              <span>A unique readable name is suggested for every new build.</span>
            </div>
            <label htmlFor="project-prompt">
              {selectedJob ? "Ask for a change or start another build" : "Describe the software you want to build"}
            </label>
            <textarea
              id="project-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Build a customer portal with authentication, billing, analytics and an admin dashboard…"
              rows={4}
            />
            <input
              ref={mediaInputRef}
              className="studio-media-input"
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp,video/mp4,video/webm,video/ogg"
              multiple
              onChange={(event) => {
                void handleMediaSelection(event.currentTarget.files);
                event.currentTarget.value = "";
              }}
            />
            <div className="studio-intake-tools">
              <button
                type="button"
                onClick={() => mediaInputRef.current?.click()}
                disabled={uploadBusy || busy}
              >
                <Paperclip size={14} aria-hidden="true" />
                {uploadBusy ? "Uploading" : "Add photos or videos"}
              </button>
              {!recording ? (
                <button
                  type="button"
                  onClick={() => void startVoiceRecording()}
                  disabled={transcribing || busy}
                >
                  <Mic size={14} aria-hidden="true" />
                  {transcribing ? "Transcribing" : "Speak prompt"}
                </button>
              ) : (
                <>
                  <button className="recording" type="button" onClick={() => stopVoiceRecording()}>
                    <Square size={12} aria-hidden="true" />
                    Stop {formatDuration(recordingSeconds)}
                  </button>
                  <button type="button" onClick={() => stopVoiceRecording(true)}>
                    <X size={14} aria-hidden="true" />
                    Cancel
                  </button>
                </>
              )}
              <span>Review and edit the transcript before building.</span>
            </div>
            {uploadedAssets.length ? (
              <div className="studio-upload-list" aria-label="Attached media">
                {uploadedAssets.map((asset) => (
                  <div key={asset.asset_id}>
                    {asset.kind === "image" ? <ImageIcon size={14} /> : <Film size={14} />}
                    <span>{asset.filename}</span>
                    <small>{formatBytes(asset.bytes)}</small>
                    <button
                      type="button"
                      aria-label={`Remove ${asset.filename}`}
                      onClick={() => void handleRemoveMedia(asset.asset_id)}
                    >
                      <X size={13} aria-hidden="true" />
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="studio-profile-selector" aria-label="Generation mode">
              {(["auto", "standard", "advanced"] as GenerationProfile[]).map((profile) => (
                <button
                  key={profile}
                  className={generationProfile === profile ? "active" : ""}
                  type="button"
                  onClick={() => selectGenerationProfile(profile)}
                >
                  <strong>{profile === "auto" ? "Auto" : profile === "standard" ? "Standard" : "Advanced"}</strong>
                  <span>
                    {profile === "auto"
                      ? "Recommended routing"
                      : profile === "standard"
                        ? "Small, focused builds"
                        : "Full-stack and media-heavy"}
                  </span>
                </button>
              ))}
            </div>
            <div className="studio-composer-actions">
              <details>
                <summary>Advanced</summary>
                <div className="studio-advanced-controls">
                  <label htmlFor="capability-id">Stack</label>
                  <select
                    id="capability-id"
                    value={capabilityId}
                    onChange={(event) => setCapabilityId(event.target.value)}
                  >
                    {certifiedStacks.map(([value, label]) => (
                      <option key={value || "auto"} value={value}>{label}</option>
                    ))}
                  </select>
                  <label className="run-toggle" htmlFor="run-now">
                    <input
                      id="run-now"
                      type="checkbox"
                      checked={runImmediately}
                      onChange={(event) => setRunImmediately(event.target.checked)}
                    />
                    Run immediately
                  </label>
                </div>
              </details>
              <span>
                {wordCount(prompt)} words
                {transcriptionCost > 0 ? ` · voice est. $${transcriptionCost.toFixed(4)}` : ""}
              </span>
              <button
                disabled={busy || uploadBusy || transcribing || recording || !prompt.trim()}
                type="submit"
              >
                {busy ? <RefreshCw className="studio-spinner" size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
                {busy ? "Building" : "Build"}
              </button>
            </div>
            {!selectedJob ? (
              <div className="studio-template-row">
                {templates.map((template) => (
                  <button key={template} type="button" onClick={() => setPrompt(templatePrompt(template))}>
                    {template}
                  </button>
                ))}
              </div>
            ) : null}
          </form>
        </aside>

        <section className="studio-canvas" aria-label="Generated application workspace">
          <header className="studio-canvas-toolbar">
            <nav aria-label="Workspace views">
              <button
                className={workspaceView === "preview" ? "active" : ""}
                type="button"
                onClick={() => setWorkspaceView("preview")}
              >
                <Monitor size={15} aria-hidden="true" />
                Preview
              </button>
              <button
                className={workspaceView === "files" ? "active" : ""}
                type="button"
                onClick={() => setWorkspaceView("files")}
              >
                <FileCode2 size={15} aria-hidden="true" />
                Code
              </button>
              <button
                className={workspaceView === "activity" ? "active" : ""}
                type="button"
                onClick={() => setWorkspaceView("activity")}
              >
                <Layers3 size={15} aria-hidden="true" />
                Activity
              </button>
              <button
                className={workspaceView === "controls" ? "active" : ""}
                type="button"
                onClick={() => setWorkspaceView("controls")}
              >
                <ShieldCheck size={15} aria-hidden="true" />
                Publish
              </button>
            </nav>
            <div className="studio-canvas-meta">
              {selectedJob?.project_spec?.capability_id ? (
                <span>{selectedJob.project_spec.capability_id}</span>
              ) : (
                <span>Stack auto-detect</span>
              )}
              <span>{collaboratorCount} live</span>
            </div>
          </header>

          <div className="studio-canvas-content" data-view={workspaceView}>
            {workspaceView === "preview" ? (
              <PreviewWorkspace
                busy={previewBusy}
                job={selectedJob}
                logs={previewLogs}
                onLoadLogs={handleLoadPreviewLogs}
                onStart={handleStartPreview}
                onStop={handleStopPreview}
                preview={previewRecord}
              />
            ) : null}

            {workspaceView === "files" ? (
              <ArtifactInspector
                error={artifactError}
                files={generatedFiles}
                job={selectedJob}
                onSelectFile={(path) => selectedJob && handleSelectGeneratedFile(selectedJob.job_id, path)}
                onChangePreview={(value) => {
                  setFilePreview(value);
                  setFileDirty(true);
                }}
                onSave={handleSaveGeneratedFile}
                preview={filePreview}
                dirty={fileDirty}
                busy={busy}
                collaboratorCount={collaboratorCount}
                selectedPath={selectedFilePath}
              />
            ) : null}

            {workspaceView === "activity" ? (
              <div className="studio-activity-layout">
                <section className="studio-graph-card" aria-label="Interactive workflow graph">
                  <div className="studio-section-heading">
                    <div>
                      <p>Build activity</p>
                      <h2>Agent orchestration</h2>
                    </div>
                    <button type="button" onClick={handleRunNext} disabled={busy}>
                      <ChevronRight size={14} aria-hidden="true" />
                      Run next
                    </button>
                  </div>
                  <WorkflowGraph nodes={nodes} activeNodeId={activeNode.id} onSelect={setActiveNodeId} />
                </section>
                <aside className="studio-activity-detail">
                  <ActiveAgentCard node={activeNode} selectedJob={selectedJob} />
                  <section className="studio-output-card">
                    <div>
                      <h3>Agent output</h3>
                      <span data-status={activeNode.status}>{activeNode.status}</span>
                    </div>
                    <pre>{selectedOutput || "Agent output will appear during the workflow."}</pre>
                    <details>
                      <summary>Tool calls</summary>
                      <pre>{JSON.stringify(selectedToolCalls, null, 2)}</pre>
                    </details>
                  </section>
                </aside>
              </div>
            ) : null}

            {workspaceView === "controls" ? (
              <div className="studio-control-stack">
                <DesignTokenPanel job={selectedJob} />
                <ReleaseCenter job={selectedJob} />
                <GuardrailInspector job={selectedJob} />
              </div>
            ) : null}
          </div>
        </section>
      </main>
    </div>
  );
}

function BuildConversation({ job, nodes }: { job: JobState | null; nodes: StudioNode[] }) {
  if (!job) {
    return (
      <div className="studio-welcome-message">
        <span><Sparkles size={18} aria-hidden="true" /></span>
        <h2>Build complete software through conversation.</h2>
        <p>
          Describe the product and Agentic Forge will plan the architecture, generate the frontend,
          backend and database, verify the result, and prepare a runnable project.
        </p>
        <div>
          <span><Check size={12} aria-hidden="true" /> Frontend</span>
          <span><Check size={12} aria-hidden="true" /> Backend</span>
          <span><Check size={12} aria-hidden="true" /> Database</span>
          <span><Check size={12} aria-hidden="true" /> QA</span>
        </div>
      </div>
    );
  }

  const completed = nodes.filter((node) => node.status === "complete").length;
  const latestResult = job.worker_results[job.worker_results.length - 1];

  return (
    <>
      <article className="studio-message studio-message-user">
        <span>You</span>
        <p>{job.request.prompt}</p>
      </article>
      <article className="studio-message studio-message-agent">
        <header>
          <span className="brand-mark"><TerminalSquare size={14} aria-hidden="true" /></span>
          <div>
            <strong>Agentic Forge</strong>
            <em>{job.status.replace(/_/g, " ")}</em>
          </div>
          <span>{completed}/{nodes.length}</span>
        </header>
        <p>{conversationSummary(job, latestResult?.summary)}</p>
        <div className="studio-stage-list">
          {nodes.map((node) => (
            <div key={node.id} data-status={node.status}>
              <span>{node.status === "complete" ? <Check size={11} /> : node.order}</span>
              <strong>{node.title}</strong>
              <em>{node.status}</em>
            </div>
          ))}
        </div>
        {job.errors.length > 0 ? <p className="studio-message-error">{job.errors[job.errors.length - 1]}</p> : null}
        {job.warnings.length > 0 ? <p>{job.warnings[job.warnings.length - 1]}</p> : null}
      </article>
      {latestResult ? (
        <article className="studio-message studio-message-note">
          <strong>{latestResult.worker_kind} agent</strong>
          <p>{latestResult.summary || "The latest worker handoff is ready for review."}</p>
        </article>
      ) : null}
    </>
  );
}

function conversationSummary(job: JobState, latestSummary?: string): string {
  if (job.release_status === "quarantined" && job.artifacts.length > 0) {
    return "The project was generated and is available in an isolated red-state preview and ZIP, but external publication is locked.";
  }
  if (job.release_status === "provisional" && job.artifacts.length > 0) {
    return "The latest project was preserved for preview and download with validation warnings.";
  }
  if (job.status === "succeeded") {
    return "The build passed evaluation. Start the preview, inspect the files, or publish the generated project.";
  }
  if (job.status === "failed" || job.status === "blocked") {
    return job.evaluation?.failure_reason ?? job.errors[job.errors.length - 1] ?? "The workflow needs attention before it can continue.";
  }
  if (job.status === "awaiting_human_feedback") {
    const gate = activeFeedbackRequest(job)?.gate;
    if (gate === "product_contract") {
      return "Planning is complete. Approve the product contract before implementation begins.";
    }
    if (gate === "privileged_action") {
      return "The workflow needs narrowly scoped permission for an external side effect.";
    }
    return "The validated release candidate is waiting for your final approval.";
  }
  if (job.status === "evaluating") {
    return "The evaluator is checking architecture, implementation, security and artifact quality.";
  }
  if (job.status === "retrying") {
    return "The evaluator found a targeted issue and the responsible worker is retrying it now.";
  }
  return latestSummary ?? "The agents are planning and building your software. Progress updates appear here automatically.";
}

function HumanCheckpointPanel({
  busy,
  feedback,
  message,
  onChangeMessage,
  onSubmit
}: {
  busy: boolean;
  feedback: HumanFeedbackRequest | null;
  message: string;
  onChangeMessage: (message: string) => void;
  onSubmit: (decision: HumanFeedbackDecision) => Promise<void>;
}) {
  if (!feedback) {
    return null;
  }

  const diagramSource =
    typeof feedback.metadata.diagram_source === "string" ? feedback.metadata.diagram_source : "";
  const visualIsImage =
    feedback.visual_type === "svg_data_uri" && feedback.visual_content.startsWith("data:image/");

  return (
    <section className="human-checkpoint" aria-label="Human checkpoint">
      <div className="checkpoint-copy">
        <p className="section-kicker">Human checkpoint</p>
        <h3>{feedback.title}</h3>
        <p>{feedback.prompt}</p>
        <div className="checkpoint-meta">
          <span>{approvalGateLabel(feedback.gate)}</span>
          {feedback.attempt > 0 ? <span>Attempt {feedback.attempt}</span> : null}
          <span>{feedback.status}</span>
        </div>
        <textarea
          aria-label="Requested changes"
          onChange={(event) => onChangeMessage(event.target.value)}
          placeholder="Optional note for approval, or describe the exact change you want."
          rows={4}
          value={message}
        />
        <div className="checkpoint-actions">
          <button type="button" disabled={busy} onClick={() => onSubmit("approve")}>
            <ShieldCheck size={15} aria-hidden="true" />
            {approvalButtonLabel(feedback.gate)}
          </button>
          <button type="button" disabled={busy} onClick={() => onSubmit("request_changes")}>
            <MessageSquare size={15} aria-hidden="true" />
            Request changes
          </button>
        </div>
      </div>
      <div className="checkpoint-visual">
        {visualIsImage ? (
          <img src={feedback.visual_content} alt={`${feedback.title} visual preview`} />
        ) : (
          <pre>{feedback.visual_content}</pre>
        )}
        {diagramSource ? <pre className="diagram-source">{diagramSource}</pre> : null}
      </div>
    </section>
  );
}

function GuardrailInspector({ job }: { job: JobState | null }) {
  const reports = latestGuardrailReports(job?.guardrail_reports ?? []);
  const findings = reports.flatMap((report) =>
    report.findings.map((finding) => ({ report, finding }))
  );
  const suppressedCount = findings.filter(
    ({ finding }) => finding.metadata?.classification === "suppressed_false_positive"
  ).length;
  const blockingCount = findings.filter(({ finding }) => !finding.passed).length;

  return (
    <div className="guardrail-inspector">
      <div className="artifact-header">
        <div>
          <p className="section-kicker">Security / QA</p>
          <h3>Guardrail findings</h3>
        </div>
        <span data-status={blockingCount ? "blocked" : "succeeded"}>
          {blockingCount ? `${blockingCount} blocking` : "passing"}
        </span>
      </div>

      {!job ? <p className="artifact-empty">Run a workflow to inspect security decisions.</p> : null}
      {job && findings.length === 0 ? (
        <p className="artifact-empty">No guardrail findings have been recorded yet.</p>
      ) : null}

      {suppressedCount > 0 ? (
        <p className="guardrail-note">
          {suppressedCount} suspected false positive candidate
          {suppressedCount === 1 ? " was" : "s were"} recorded and allowed.
        </p>
      ) : null}

      <div className="guardrail-finding-list">
        {findings.map(({ report, finding }, index) => {
          const samples = Array.isArray(finding.metadata?.samples)
            ? finding.metadata.samples.map(String)
            : [];
          const reasons = Array.isArray(finding.metadata?.reasons)
            ? finding.metadata.reasons.map(String)
            : [];
          const classification =
            typeof finding.metadata?.classification === "string"
              ? finding.metadata.classification
              : finding.passed
                ? "passed"
                : "blocking";

          return (
            <article
              className={`guardrail-finding ${finding.passed ? "allowed" : "blocked"}`}
              key={`${report.name}-${finding.name}-${index}`}
            >
              <div>
                <strong>{finding.name}</strong>
                <span>{report.name}</span>
                <em>{classification.replace(/_/g, " ")}</em>
              </div>
              <p>{finding.message}</p>
              {reasons.length > 0 ? <p>Reason: {reasons.join("; ")}</p> : null}
              {samples.length > 0 ? (
                <code>{samples.slice(0, 3).join(", ")}</code>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function ArtifactInspector({
  busy,
  collaboratorCount,
  dirty,
  error,
  files,
  job,
  onSelectFile,
  onChangePreview,
  onSave,
  preview,
  selectedPath
}: {
  busy: boolean;
  collaboratorCount: number;
  dirty: boolean;
  error: string | null;
  files: GeneratedFile[];
  job: JobState | null;
  onSelectFile: (path: string) => void;
  onChangePreview: (value: string) => void;
  onSave: () => Promise<void>;
  preview: string;
  selectedPath: string | null;
}) {
  const archive = job?.artifacts?.find((artifact) => artifact.kind === "zip");
  const failureMessages = [
    ...(job?.artifact_errors ?? []),
    ...(job?.errors ?? []),
    ...(job?.evaluation?.failure_reason ? [job.evaluation.failure_reason] : [])
  ].filter((message, index, messages) => messages.indexOf(message) === index);

  return (
    <div className="artifact-inspector">
      <div className="artifact-header">
        <div>
          <p className="section-kicker">Generated output</p>
          <h3>Project package</h3>
        </div>
        {job && archive ? (
          <div className="artifact-actions">
            <span>{collaboratorCount} live</span>
            <button type="button" disabled={busy || !dirty} onClick={onSave}>
              <Save size={14} aria-hidden="true" />
              {dirty ? "Save" : "Saved"}
            </button>
            <a href={generatedProjectDownloadUrl(job.job_id)}>
              <Download size={15} aria-hidden="true" />
              ZIP
            </a>
          </div>
        ) : null}
      </div>

      {job && archive ? (
        <p className="release-banner" data-release={job.release_status}>
          {job.release_status === "verified"
            ? "Verified build — preview, download, and publication are enabled."
            : job.release_status === "quarantined"
              ? "Quarantined build — preview and ZIP download are enabled; publication is locked."
              : "Provisional build — the latest filesystem is preserved with validation warnings."}
        </p>
      ) : null}

      {!job ? <p className="artifact-empty">Run a workflow to generate a project folder and ZIP.</p> : null}
      {job && files.length === 0 ? (
        <p className="artifact-empty">
          {failureMessages.length > 0
            ? failureMessages.join(" ")
            : job.status === "succeeded"
            ? "Generated files will appear here when artifacts are available."
            : "Artifacts are created only after the evaluator marks the workflow successful."}
        </p>
      ) : null}
      {error ? <p className="artifact-error">{error}</p> : null}

      {files.length > 0 ? (
        <div className="artifact-layout">
          <div className="file-list" aria-label="Generated project files">
            {files.map((file) => (
              <button
                className={selectedPath === file.path ? "selected" : ""}
                key={file.path}
                type="button"
                onClick={() => onSelectFile(file.path)}
              >
                <FileCode2 size={14} aria-hidden="true" />
                <span>{file.path}</span>
                <em>{formatBytes(file.size)}</em>
              </button>
            ))}
          </div>
          <textarea
            aria-label="Generated file editor"
            className="file-preview file-editor"
            onChange={(event) => onChangePreview(event.target.value)}
            readOnly={!selectedPath || !isPreviewable(selectedPath)}
            spellCheck={false}
            value={preview || ""}
          />
        </div>
      ) : null}
    </div>
  );
}

function PreviewWorkspace({
  busy,
  job,
  logs,
  onLoadLogs,
  onStart,
  onStop,
  preview
}: {
  busy: boolean;
  job: JobState | null;
  logs: string;
  onLoadLogs: () => Promise<void>;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
  preview: PreviewRecord | null;
}) {
  const [iframeFailed, setIframeFailed] = useState(false);
  const primaryService =
    preview?.services.find((service) => service.name === "frontend") ?? preview?.services[0];
  const canPreview = job?.artifacts.some((artifact) => artifact.kind === "folder") ?? false;
  useEffect(() => {
    setIframeFailed(false);
  }, [primaryService?.url]);

  return (
    <section className="preview-workspace" aria-label="Live generated application preview">
      <div className="preview-toolbar">
        <div>
          <p className="section-kicker">Sandbox preview</p>
          <h3>Run the generated application</h3>
        </div>
        <div className="preview-actions">
          <span data-status={preview?.status ?? "stopped"}>
            {preview?.sandbox_mode ?? "local"} · {preview?.status ?? "stopped"}
          </span>
          {preview?.status === "running" ? (
            <button type="button" disabled={busy} onClick={onStop}>Stop</button>
          ) : (
            <button type="button" disabled={busy || !canPreview} onClick={onStart}>
              <Play size={14} aria-hidden="true" />
              {busy ? "Starting…" : "Start preview"}
            </button>
          )}
          {primaryService ? (
            <a href={primaryService.url} target="_blank" rel="noreferrer">
              Open <ExternalLink size={13} aria-hidden="true" />
            </a>
          ) : null}
        </div>
      </div>
      {preview?.status === "running" && primaryService && !iframeFailed ? (
        <iframe
          src={primaryService.url}
          sandbox="allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
          title="Generated application preview"
          referrerPolicy="no-referrer"
          onError={() => setIframeFailed(true)}
        />
      ) : iframeFailed && preview?.screenshot_path ? (
        <div className="preview-screenshot-fallback">
          <img
            alt="Last verified headless-browser preview"
            src={previewScreenshotUrl(preview.job_id)}
          />
          <p>The live frame could not load. Showing the last verified sandbox screenshot.</p>
        </div>
      ) : (
        <div className="preview-placeholder">
          {preview?.error ?? "Start the isolated runtime to test the generated app here."}
        </div>
      )}
      {preview?.quarantined ? (
        <p className="quarantine-banner">
          Red-state runtime: isolated Docker preview only. GitHub and deployment remain disabled.
        </p>
      ) : null}
      {preview?.checks?.length ? (
        <div className="runtime-checks" aria-label="Sandbox runtime checks">
          {preview.checks.map((check) => (
            <span data-passed={check.passed} key={check.name} title={check.message}>
              {check.name.replace(/_/g, " ")} · {check.passed ? "passed" : "warning"}
            </span>
          ))}
        </div>
      ) : null}
      {preview ? (
        <details className="preview-logs" onToggle={(event) => {
          if (event.currentTarget.open && !logs) void onLoadLogs();
        }}>
          <summary>Runtime logs and service URLs</summary>
          <div className="preview-service-list">
            {preview.services.map((service) => (
              <a href={service.url} key={service.name} target="_blank" rel="noreferrer">
                {service.name}: {service.url}
              </a>
            ))}
          </div>
          <pre>{logs || "Loading logs…"}</pre>
        </details>
      ) : null}
    </section>
  );
}

function DesignTokenPanel({ job }: { job: JobState | null }) {
  const [files, setFiles] = useState<DesignTokenFile[]>([]);
  const [activePath, setActivePath] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const active = files.find((file) => file.path === activePath) ?? files[0];

  useEffect(() => {
    const jobId = job?.job_id;
    if (!jobId || !job.artifacts.some((artifact) => artifact.kind === "folder")) {
      setFiles([]);
      setActivePath("");
      setDraft({});
      return;
    }
    void listDesignTokens(jobId)
      .then(({ files: nextFiles }) => {
        setFiles(nextFiles);
        setActivePath(nextFiles[0]?.path ?? "");
        setDraft(nextFiles[0]?.tokens ?? {});
      })
      .catch(() => setFiles([]));
  }, [job?.job_id, job?.artifacts?.length]);

  useEffect(() => {
    if (active) {
      setDraft(active.tokens);
    }
  }, [active?.path, active?.sha256]);

  async function saveTokens() {
    if (!job || !active) {
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const updated = await updateDesignTokens(
        job.job_id,
        active.path,
        draft,
        active.sha256
      );
      setFiles((current) => current.map((file) => file.path === updated.path ? updated : file));
      setMessage("Design tokens saved; a running preview reloads automatically.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unable to save design tokens.");
    } finally {
      setSaving(false);
    }
  }

  if (files.length === 0) {
    return null;
  }

  return (
    <section className="design-token-panel" aria-label="Visual design tokens">
      <div className="design-token-header">
        <div>
          <p className="section-kicker">Visual editor</p>
          <h3>Design tokens</h3>
        </div>
        <select
          aria-label="Design token source file"
          value={active?.path ?? ""}
          onChange={(event) => setActivePath(event.target.value)}
        >
          {files.map((file) => <option key={file.path}>{file.path}</option>)}
        </select>
        <button type="button" disabled={saving} onClick={saveTokens}>
          <Save size={14} aria-hidden="true" />
          {saving ? "Saving…" : "Apply tokens"}
        </button>
      </div>
      <div className="design-token-grid">
        {Object.entries(draft).map(([name, value]) => (
          <label key={name}>
            <span>--{name}</span>
            <div>
              {/^#[0-9a-f]{6}$/i.test(value) ? (
                <input
                  aria-label={`${name} color`}
                  type="color"
                  value={value}
                  onChange={(event) => setDraft((current) => ({ ...current, [name]: event.target.value }))}
                />
              ) : null}
              <input
                value={value}
                onChange={(event) => setDraft((current) => ({ ...current, [name]: event.target.value }))}
              />
            </div>
          </label>
        ))}
      </div>
      {message ? <p>{message}</p> : null}
    </section>
  );
}

function ReleaseCenter({ job }: { job: JobState | null }) {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [owner, setOwner] = useState("");
  const [repository, setRepository] = useState("");
  const [branch, setBranch] = useState("agentic-forge");
  const [projectName, setProjectName] = useState("");
  const [supabaseOrganization, setSupabaseOrganization] = useState("");
  const [databasePassword, setDatabasePassword] = useState("");
  const [confirmBilling, setConfirmBilling] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [result, setResult] = useState("");
  const publicationLocked = Boolean(job && job.release_status !== "verified");

  useEffect(() => {
    void listProviderStatus().then(setProviders).catch(() => setProviders([]));
  }, []);

  useEffect(() => {
    const slug = (job?.request.project_id ?? "generated-app")
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-|-$/g, "");
    setProjectName(slug || "generated-app");
  }, [job?.job_id]);

  const ready = (provider: ProviderStatus["provider"]) => {
    const status = providers.find((item) => item.provider === provider);
    return Boolean(status?.configured && status.enabled);
  };

  async function runAction(name: string, action: () => Promise<Record<string, unknown>>) {
    setBusyAction(name);
    setResult("");
    try {
      setResult(JSON.stringify(await action(), null, 2));
      if (name === "supabase") {
        setDatabasePassword("");
        setConfirmBilling(false);
      }
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Provider action failed.");
    } finally {
      setBusyAction("");
    }
  }

  return (
    <section className="release-center" aria-label="Source control and managed services center">
      <div className="release-header">
        <div>
          <p className="section-kicker">Release center</p>
          <h3>Source control and managed services</h3>
        </div>
        <div className="provider-statuses">
          {providers.map((provider) => (
            <a href={provider.documentation_url} key={provider.provider} target="_blank" rel="noreferrer">
              <i data-ready={provider.configured && provider.enabled} />
              {provider.provider}
            </a>
          ))}
        </div>
      </div>
      <div className="release-grid">
        <form onSubmit={(event) => {
          event.preventDefault();
          if (job) void runAction("github", () => syncToGitHub(job.job_id, {
            owner,
            repository,
            branch,
            create_pull_request: true
          }));
        }}>
          <strong>GitHub sync + pull request</strong>
          <input placeholder="Owner" required value={owner} onChange={(event) => setOwner(event.target.value)} />
          <input placeholder="Repository" required value={repository} onChange={(event) => setRepository(event.target.value)} />
          <input placeholder="Branch" required value={branch} onChange={(event) => setBranch(event.target.value)} />
          <button disabled={!job || publicationLocked || !ready("github") || Boolean(busyAction)} type="submit">
            <Github size={14} aria-hidden="true" /> Sync repository
          </button>
        </form>
        <form onSubmit={(event) => {
          event.preventDefault();
          void runAction("supabase", () => createSupabaseProject({
            name: projectName,
            organization_slug: supabaseOrganization,
            database_password: databasePassword,
            confirm_billing: confirmBilling
          }));
        }}>
          <strong>Supabase project</strong>
          <input placeholder="Organization slug" required value={supabaseOrganization} onChange={(event) => setSupabaseOrganization(event.target.value)} />
          <input autoComplete="new-password" minLength={12} placeholder="Database password" required type="password" value={databasePassword} onChange={(event) => setDatabasePassword(event.target.value)} />
          <label className="billing-confirmation">
            <input type="checkbox" checked={confirmBilling} onChange={(event) => setConfirmBilling(event.target.checked)} />
            I confirm this may create billable resources.
          </label>
          <button disabled={!ready("supabase") || !confirmBilling || Boolean(busyAction)} type="submit">
            <Database size={14} aria-hidden="true" /> Provision project
          </button>
        </form>
      </div>
      {!providers.some((provider) => provider.configured && provider.enabled) ? (
        <p>Provider actions are locked. Configure credentials and set ENABLE_PROVIDER_ACTIONS=true.</p>
      ) : null}
      {publicationLocked ? (
        <p>
          GitHub publication is locked for {job?.release_status} builds. Preview and ZIP download remain available.
        </p>
      ) : null}
      {result ? <pre>{result}</pre> : null}
    </section>
  );
}

function WorkflowGraph({
  nodes,
  activeNodeId,
  onSelect
}: {
  nodes: StudioNode[];
  activeNodeId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="workflow-graph">
      <svg className="route-map" viewBox="0 0 390 520" role="img" aria-label="Agent orchestration route">
        <path className="route-main" d="M98 38 L98 480" />
        <path className="route-loop" d="M98 128 C24 166 22 262 98 286 C178 314 162 410 98 444" />
        <path className="route-loop route-secondary" d="M98 206 C182 228 198 320 98 352" />
        <path className="route-branch" d="M98 206 C172 184 232 205 282 244" />
        <path className="route-branch route-secondary" d="M98 286 C174 286 232 332 286 386" />
      </svg>
      <div className="graph-node-list">
        {nodes.map((node) => (
          <button
            className={`graph-node ${node.status} ${activeNodeId === node.id ? "selected" : ""}`}
            key={node.id}
            type="button"
            onClick={() => onSelect(node.id)}
          >
            <span className="node-orb">{node.status === "complete" ? <Check size={14} /> : node.order}</span>
            <span className="node-icon">{nodeIcon(node.id)}</span>
            <strong>{node.title}</strong>
            <em>{node.status}</em>
          </button>
        ))}
      </div>
      <p className="graph-caption">Agent orchestration graph / event stream / shared context</p>
    </div>
  );
}

function ActiveAgentCard({ node, selectedJob }: { node: StudioNode; selectedJob: JobState | null }) {
  const currentTask = selectedJob?.tasks.find((task) => task.worker_kind === node.workerKind);
  const taskText = currentTask?.instructions.split("\n").find((line) => line.startsWith("Request:"));

  return (
    <article className="active-agent-card">
      <div className="active-card-header">
        <span>{nodeInitials(node.title)}</span>
        <div>
          <p>Active agent</p>
          <h3>{node.role}</h3>
        </div>
        <em>{node.status === "active" ? "Building" : node.status}</em>
      </div>
      <dl>
        <div>
          <dt>Current task</dt>
          <dd>{taskText?.replace("Request:", "").trim() || node.description}</dd>
        </div>
        <div>
          <dt>Stack</dt>
          <dd>{node.stack}</dd>
        </div>
      </dl>
      <div className="progress-row">
        <span>Build progress</span>
        <strong>{node.progress}%</strong>
      </div>
      <div className="progress-track">
        <span style={{ width: `${node.progress}%` }} />
      </div>
      <div className="agent-logline">
        <ChevronRight size={14} aria-hidden="true" />
        <span>
          {node.status === "complete"
            ? "Verified output ready for downstream handoff"
            : node.status === "failed" || node.status === "blocked"
              ? "Review required before retry"
              : "Generating plan, code, checks and handoff notes"}
        </span>
      </div>
    </article>
  );
}

function StatsStrip({ metrics, selectedJob }: { metrics: Metrics | null; selectedJob: JobState | null }) {
  const completed = selectedJob ? buildNodes(selectedJob).filter((node) => node.status === "complete").length : 1;
  const successRate = metrics?.jobs_submitted
    ? Math.round(((metrics.jobs_succeeded || 0) / metrics.jobs_submitted) * 100)
    : 100;

  return (
    <section className="stats-strip">
      <div>
        <strong>{String(completed).padStart(2, "0")}</strong>
        <span>Structured planning before code generation</span>
      </div>
      <div>
        <strong>06</strong>
        <span>Specialized agents with shared project memory</span>
      </div>
      <div>
        <strong>24/7</strong>
        <span>Continuous build, testing and observability</span>
      </div>
      <div>
        <strong>{successRate}%</strong>
        <span>Exportable code with your own repository</span>
      </div>
    </section>
  );
}

function buildNodes(job: JobState | null): StudioNode[] {
  const taskStatus = (kind: WorkerKind): TaskStatus | undefined =>
    job?.tasks.find((task) => task.worker_kind === kind)?.status;
  const failedGuardrail = job?.release_status === "quarantined";

  return [
    {
      id: "architect",
      order: "01",
      title: "Product Architect",
      role: "Product Architect",
      description: "Maps the prompt into requirements, agent scopes and acceptance checks.",
      stack: "Planning · LangGraph · Shared memory",
      status: activeFeedbackRequest(job)?.gate === "product_contract" ? "review" : job ? "complete" : "active",
      progress: activeFeedbackRequest(job)?.gate === "product_contract" ? 88 : job ? 100 : 32
    },
    {
      id: "frontend",
      order: "02",
      title: "Frontend Agent",
      role: "Interface Engineer",
      description: "Builds responsive React surfaces and verifies user flows.",
      stack: "React · Vite · TypeScript",
      status: statusFromTask(taskStatus("frontend"), job, false, "frontend"),
      progress: progressFromTask(taskStatus("frontend"), job, false, "frontend"),
      workerKind: "frontend"
    },
    {
      id: "backend",
      order: "03",
      title: "Backend Agent",
      role: "Backend Engineer",
      description: "Generates production APIs, queues, services and integration boundaries.",
      stack: "FastAPI · PostgreSQL · Redis",
      status: statusFromTask(taskStatus("backend"), job, true, "backend"),
      progress: progressFromTask(taskStatus("backend"), job, true, "backend"),
      workerKind: "backend"
    },
    {
      id: "database",
      order: "04",
      title: "Database Agent",
      role: "Data Engineer",
      description: "Designs schemas, migrations, indexes, cache paths and retrieval memory.",
      stack: "Supabase · pgvector · SQL",
      status: statusFromTask(taskStatus("database"), job, false, "database"),
      progress: progressFromTask(taskStatus("database"), job, false, "database"),
      workerKind: "database"
    },
    {
      id: "security",
      order: "05",
      title: "Security + QA",
      role: "Verification Engineer",
      description: "Runs guardrails, tests, vulnerability checks and output verification.",
      stack: "Guardrails · Pytest · Playwright",
      status: activeFeedbackRequest(job)?.gate === "privileged_action"
        ? "review"
        : securityStatus(job, failedGuardrail),
      progress: failedGuardrail ? 100 : job?.evaluation ? 100 : job ? 58 : 0
    },
    {
      id: "packaging",
      order: "06",
      title: "Packaging Agent",
      role: "Artifact Engineer",
      description: "Packages validated source, dependency manifests, instructions and downloadable artifacts.",
      stack: "Validation · ZIP · README",
      status: activeFeedbackRequest(job)?.gate === "release"
        ? "review"
        : job?.artifacts.length
        ? job.release_status === "quarantined"
          ? "blocked"
          : "complete"
        : job?.status === "failed"
          ? "failed"
          : "queued",
      progress: job?.artifacts.length ? 100 : 0
    }
  ];
}

function statusFromTask(
  status: TaskStatus | undefined,
  job: JobState | null,
  fallbackActive = false,
  workerKind?: WorkerKind
): NodeStatus {
  const feedback = activeFeedbackRequest(job);
  if (feedback?.worker_kind === workerKind) {
    return "review";
  }
  if (status === "succeeded") {
    return "complete";
  }
  if (status === "failed") {
    return "failed";
  }
  if (status === "running") {
    return "active";
  }
  if (status === "pending") {
    return job?.status === "running" || fallbackActive ? "active" : "queued";
  }
  if (!job && fallbackActive) {
    return "active";
  }
  return "queued";
}

function progressFromTask(
  status: TaskStatus | undefined,
  job: JobState | null,
  fallbackActive = false,
  workerKind?: WorkerKind
): number {
  const feedback = activeFeedbackRequest(job);
  if (feedback?.worker_kind === workerKind) {
    return 88;
  }
  if (status === "succeeded") {
    return 100;
  }
  if (status === "failed") {
    return 100;
  }
  if (status === "running" || status === "pending" || (!job && fallbackActive)) {
    return 42;
  }
  return 0;
}

function securityStatus(job: JobState | null, failedGuardrail: boolean): NodeStatus {
  if (!job) {
    return "queued";
  }
  if (failedGuardrail || job.status === "blocked") {
    return "blocked";
  }
  if (job.status === "evaluating") {
    return "active";
  }
  if (job.evaluation || job.status === "succeeded") {
    return "complete";
  }
  return "queued";
}

function latestGuardrailReports(reports: JobState["guardrail_reports"]): JobState["guardrail_reports"] {
  const latest = new Map<string, JobState["guardrail_reports"][number]>();
  [...reports].reverse().forEach((report) => {
    if (!latest.has(report.name)) latest.set(report.name, report);
  });
  return [...latest.values()];
}

function firstActiveNode(nodes: StudioNode[]): StudioNode {
  return (
    nodes.find((node) => node.status === "active") ??
    nodes.find((node) => node.status === "review") ??
    nodes.find((node) => node.status === "failed" || node.status === "blocked") ??
    nodes.find((node) => node.id === "backend") ??
    nodes[0]
  );
}

function activeFeedbackRequest(job: JobState | null): HumanFeedbackRequest | null {
  if (!job?.active_feedback_request_id) {
    return null;
  }
  return (
    job.feedback_requests.find(
      (request) =>
        request.checkpoint_id === job.active_feedback_request_id &&
        request.status === "pending"
    ) ?? null
  );
}

function approvalGateLabel(gate: HumanFeedbackRequest["gate"]): string {
  if (gate === "product_contract") return "Scope review";
  if (gate === "privileged_action") return "Scoped permission";
  if (gate === "release") return "Release approval";
  return "Worker review";
}

function approvalButtonLabel(gate: HumanFeedbackRequest["gate"]): string {
  if (gate === "product_contract") return "Approve and start";
  if (gate === "privileged_action") return "Approve scoped actions";
  if (gate === "release") return "Approve release";
  return "Approve";
}

function nodeIcon(id: string) {
  const size = 16;
  if (id === "frontend") return <Monitor size={size} aria-hidden="true" />;
  if (id === "backend") return <Code2 size={size} aria-hidden="true" />;
  if (id === "database") return <Database size={size} aria-hidden="true" />;
  if (id === "security") return <ShieldCheck size={size} aria-hidden="true" />;
  if (id === "packaging") return <Download size={size} aria-hidden="true" />;
  return <Layers3 size={size} aria-hidden="true" />;
}

function nodeInitials(title: string): string {
  return title
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function preferredRecordingMimeType(): string {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find(
    (mimeType) => MediaRecorder.isTypeSupported(mimeType)
  ) ?? "";
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function contextEstimate(text: string): number {
  return Math.min(96, Math.max(18, Math.round((text.length / 220) * 70)));
}

function isPreviewable(path: string): boolean {
  return /\.(css|env|html|js|jsx|json|md|py|sql|toml|tsx?|ya?ml)$/i.test(path);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function sha256(content: string): Promise<string> {
  const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(content));
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function templatePrompt(template: string): string {
  if (template === "Realtime workspace") {
    return "Build a realtime team workspace with projects, comments, activity feed and admin roles.";
  }
  if (template === "AI support platform") {
    return "Build an AI support platform with ticket routing, knowledge search and analytics.";
  }
  return "Build a developer portal with API keys, usage charts, docs and billing controls.";
}
