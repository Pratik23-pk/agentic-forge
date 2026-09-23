import {
  ArrowRight,
  ChevronDown,
  CirclePlay,
  Code2,
  Crosshair,
  Monitor,
  Play,
  ShieldCheck,
  Sparkles,
  Star
} from "lucide-react";
import {
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState
} from "react";

interface LandingPageProps {
  onEnterStudio: (event: MouseEvent<HTMLAnchorElement>) => void;
}

interface OrbitAgent {
  id: string;
  label: string;
  phase: number;
  radiusX: number;
  radiusY: number;
  hue: string;
  accent: string;
  labelSide: "left" | "right";
  icon: ReactNode;
}

const orbitAgents: OrbitAgent[] = [
  {
    id: "plan",
    label: "Plan",
    phase: Math.PI * 1.12,
    radiusX: 31,
    radiusY: 26,
    hue: "#03c8ff",
    accent: "#2965ff",
    labelSide: "left",
    icon: <Crosshair size={26} strokeWidth={1.8} aria-hidden="true" />
  },
  {
    id: "build",
    label: "Build",
    phase: Math.PI * 0.77,
    radiusX: 42,
    radiusY: 34,
    hue: "#00d4ff",
    accent: "#1277ff",
    labelSide: "left",
    icon: <Code2 size={31} strokeWidth={1.8} aria-hidden="true" />
  },
  {
    id: "test",
    label: "Test",
    phase: Math.PI * 1.88,
    radiusX: 34,
    radiusY: 27,
    hue: "#9d4dff",
    accent: "#5f2bff",
    labelSide: "right",
    icon: <ShieldCheck size={27} strokeWidth={1.8} aria-hidden="true" />
  },
  {
    id: "preview",
    label: "Preview",
    phase: Math.PI * 0.2,
    radiusX: 42,
    radiusY: 34,
    hue: "#c44dff",
    accent: "#7130ff",
    labelSide: "right",
    icon: <Monitor size={29} strokeWidth={1.8} aria-hidden="true" />
  }
];

export function LandingPage({ onEnterStudio }: LandingPageProps) {
  const [rotation, setRotation] = useState(0);
  const [focusedAgent, setFocusedAgent] = useState<string | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const rotationRef = useRef(0);
  const focusRef = useRef<string | null>(null);
  const releaseTimerRef = useRef<number | null>(null);

  useEffect(() => {
    focusRef.current = focusedAgent;
  }, [focusedAgent]);

  useEffect(
    () => () => {
      if (releaseTimerRef.current !== null) {
        window.clearTimeout(releaseTimerRef.current);
      }
    },
    []
  );

  useEffect(() => {
    let frame = 0;
    let previousTime = performance.now();

    function animate(time: number) {
      const delta = Math.min(time - previousTime, 32);
      previousTime = time;
      const focused = orbitAgents.find((agent) => agent.id === focusRef.current);

      if (focused) {
        const target = Math.PI / 2 - focused.phase;
        const difference = shortestAngle(target - rotationRef.current);
        rotationRef.current += difference * Math.min(0.13, delta * 0.006);
      } else {
        rotationRef.current += delta * (demoMode ? 0.00062 : 0.00014);
      }

      setRotation(rotationRef.current);
      frame = requestAnimationFrame(animate);
    }

    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [demoMode]);

  function toggleDemo() {
    setFocusedAgent(null);
    setDemoMode((active) => !active);
  }

  function focusAgent(agentId: string) {
    if (releaseTimerRef.current !== null) {
      window.clearTimeout(releaseTimerRef.current);
    }
    setFocusedAgent(agentId);
  }

  function releaseAgent(delay = 3500) {
    if (releaseTimerRef.current !== null) {
      window.clearTimeout(releaseTimerRef.current);
    }
    releaseTimerRef.current = window.setTimeout(() => {
      setFocusedAgent(null);
      releaseTimerRef.current = null;
    }, delay);
  }

  return (
    <div className={`landing-shell ${demoMode ? "is-demoing" : ""}`}>
      <div className="landing-aurora landing-aurora-left" />
      <div className="landing-aurora landing-aurora-right" />

      <header className="landing-nav">
        <a className="landing-brand" href="/" aria-label="Agentic Forge home">
          <ForgeLogo compact />
          <span>Agentic Forge</span>
        </a>

        <nav className="landing-links" aria-label="Primary navigation">
          <a href="#product">
            Product <ChevronDown size={14} aria-hidden="true" />
          </a>
          <a href="#solutions">
            Solutions <ChevronDown size={14} aria-hidden="true" />
          </a>
          <a href="#agents">Agents</a>
          <a href="#pricing">Pricing</a>
          <a href="#docs">Docs</a>
          <a href="#company">
            Company <ChevronDown size={14} aria-hidden="true" />
          </a>
        </nav>

        <div className="landing-actions">
          <span className="landing-stars" aria-label="12.4 thousand community stars">
            <Star size={15} aria-hidden="true" />
            12.4K
          </span>
          <a className="landing-signin" href="/studio" onClick={onEnterStudio}>
            Sign in
          </a>
          <a className="landing-get-started" href="/studio" onClick={onEnterStudio}>
            Get Started
            <ArrowRight size={20} aria-hidden="true" />
          </a>
        </div>
      </header>

      <main className="landing-main">
        <section className="landing-copy" id="product">
          <div className="landing-pill">
            <span>Autonomous AI Agents.</span> Real Software.
          </div>
          <h1>
            Build software
            <br />
            with <span>Agentic AI</span>
          </h1>
          <p>
            Plan, code, test, and preview full software products
            <br />
            with autonomous AI agents working end-to-end.
          </p>
          <div className="landing-hero-actions">
            <a className="landing-primary-cta" href="/studio" onClick={onEnterStudio}>
              <Sparkles size={19} aria-hidden="true" />
              Get Started for Free
            </a>
            <button className="landing-demo-button" type="button" onClick={toggleDemo}>
              {demoMode ? <Play size={18} aria-hidden="true" /> : <CirclePlay size={20} aria-hidden="true" />}
              {demoMode ? "Slow Animation" : "Watch Demo"}
            </button>
          </div>
        </section>

        <section className="orbit-stage" id="agents" aria-label="Autonomous agent workflow">
          <div className="stage-stars" />
          <div className="orbit-floor-glow" />
          <div className="orbit-rings" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </div>

          {orbitAgents.map((agent) => {
            const angle = agent.phase + rotation;
            const depth = (Math.sin(angle) + 1) / 2;
            const positionStyle = {
              "--agent-x": `${50 + Math.cos(angle) * agent.radiusX}%`,
              "--agent-y": `${47 + Math.sin(angle) * agent.radiusY}%`,
              "--agent-scale": 0.82 + depth * 0.22,
              "--agent-hue": agent.hue,
              "--agent-accent": agent.accent,
              zIndex: Math.round(depth * 50) + 20
            } as CSSProperties;
            const isFocused = focusedAgent === agent.id;

            return (
              <button
                aria-label={`${agent.label} agent`}
                aria-pressed={isFocused}
                className={`orbit-agent label-${agent.labelSide} ${isFocused ? "is-focused" : ""}`}
                key={agent.id}
                onClick={() => focusAgent(agent.id)}
                onFocus={() => focusAgent(agent.id)}
                onBlur={() => releaseAgent(160)}
                onMouseEnter={() => focusAgent(agent.id)}
                onMouseLeave={() => releaseAgent()}
                style={positionStyle}
                type="button"
              >
                <span className="agent-label">
                  <i>{agent.icon}</i>
                  {agent.label}
                </span>
                <span className="agent-connector" />
                <span className="agent-planet">
                  <span className="agent-glass">
                    <i>{agent.icon}</i>
                  </span>
                  <span className="agent-base" />
                </span>
              </button>
            );
          })}

          <div className="forge-core">
            <span className="core-halo" />
            <span className="core-platform core-platform-one" />
            <span className="core-platform core-platform-two" />
            <span className="core-globe">
              <span className="core-shine" />
              <ForgeLogo />
            </span>
          </div>
        </section>

        <div className="landing-proof" aria-label="Platform qualities">
          <span>
            <i /> Autonomous
          </span>
          <b>•</b>
          <span>Secure</span>
          <b>•</b>
          <span>Scalable</span>
        </div>
      </main>
    </div>
  );
}

function ForgeLogo({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`forge-logo ${compact ? "is-compact" : ""}`} aria-hidden="true">
      <i className="forge-logo-left" />
      <i className="forge-logo-center" />
      <i className="forge-logo-right" />
    </span>
  );
}

function shortestAngle(angle: number) {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}
