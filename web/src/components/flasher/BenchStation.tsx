/** One bench slot: a granted serial port, a live log, and the run lifecycle
 *  against the backend engine. Chromium-only (Web Serial). */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { createProgrammingRun, errorMessage } from "../../api";
import { RunClient, type RunSpec } from "../../flasher/runClient";
import { Station, type LogDir } from "../../flasher/station";
import { StatusPill } from "../Ui";

export interface StationSlotProps {
  index: number;
  productionRunId: number | null;
  scriptVersionId: number | null;
  overrideReason: string;
  operator: string;
  simPin: string;
  onRunCreated?: (runId: number) => void;
}

interface LogRow {
  dir: LogDir;
  text: string;
}

type SlotStatus = "empty" | "ready" | "busy" | "pass" | "fail" | "aborted";

export default function BenchStation(props: StationSlotProps) {
  const [station] = useState(() => new Station());
  const [status, setStatus] = useState<SlotStatus>("empty");
  const [stepLabel, setStepLabel] = useState("idle");
  const [portLabel, setPortLabel] = useState("—");
  const [progress, setProgress] = useState<number | null>(null);
  const [log, setLog] = useState<LogRow[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<{ label: string; secret: boolean; resolve: (v: string) => void } | null>(null);
  const clientRef = useRef<RunClient | null>(null);
  const logEnd = useRef<HTMLDivElement>(null);

  const pushLog = useCallback((dir: LogDir, text: string) => {
    setLog((rows) => {
      const next = [...rows, { dir, text }];
      // keep the DOM bounded; the FULL log is in Postgres
      return next.length > 1500 ? next.slice(-1000) : next;
    });
  }, []);

  useEffect(() => {
    logEnd.current?.scrollIntoView({ block: "end" });
  }, [log]);

  // Re-attach on USB re-enumeration (C6 reboot) and grey out on unplug.
  useEffect(() => {
    const onConnect = (e: Event) => station.noteConnect(e.target as SerialPort);
    const onDisconnect = (e: Event) => station.noteDisconnect(e.target as SerialPort);
    navigator.serial?.addEventListener("connect", onConnect);
    navigator.serial?.addEventListener("disconnect", onDisconnect);
    return () => {
      navigator.serial?.removeEventListener("connect", onConnect);
      navigator.serial?.removeEventListener("disconnect", onDisconnect);
    };
  }, [station]);

  const pickPort = async () => {
    try {
      await station.requestPort();
      setPortLabel(station.portLabel);
      setStatus("ready");
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const run = async () => {
    if (!props.productionRunId) {
      setError("Pick a production batch first.");
      return;
    }
    setError(null);
    setLog([]);
    setStatus("busy");
    setStepLabel("creating run…");
    let created: { run_id: number };
    try {
      created = await createProgrammingRun({
        production_run_id: props.productionRunId,
        deployment_script_version_id: props.scriptVersionId,
        operator: props.operator,
        station: `slot ${props.index + 1}`,
        override_reason: props.overrideReason,
      });
    } catch (err) {
      setError(errorMessage(err));
      setStatus("ready");
      return;
    }
    setRunId(created.run_id);
    props.onRunCreated?.(created.run_id);

    const params: Record<string, string> = {};
    if (props.simPin.trim()) params.sim_pin = props.simPin.trim();
    if (props.operator.trim()) params.operator = props.operator.trim();

    const client = new RunClient(station, created.run_id, params, {
      onSpec: (spec: RunSpec) => {
        pushLog("app", `=== ${spec.script_name} v${spec.script_version_no} — ${spec.steps.length} steps ===`);
      },
      onState: (s) => setStepLabel(`${s.index + 1}/${s.total} ${s.label}`),
      onLog: pushLog,
      onProgress: setProgress,
      onPrompt: (_field, label, secret) =>
        new Promise<string>((resolve) => setPrompt({ label, secret, resolve })),
      onDone: (st, err) => {
        setStatus(st === "pass" ? "pass" : st === "aborted" ? "aborted" : "fail");
        setStepLabel(st);
        if (err) setError(err);
      },
    });
    clientRef.current = client;
    try {
      await client.start();
    } catch (err) {
      setError(errorMessage(err));
      setStatus("fail");
    } finally {
      clientRef.current = null;
    }
  };

  const abort = () => clientRef.current?.abort();

  const answerPrompt = (value: string) => {
    prompt?.resolve(value);
    setPrompt(null);
  };

  return (
    <div className="card pad bench-station">
      <div className="toolbar">
        <strong>Station {props.index + 1}</strong>
        <StatusPill status={status === "empty" ? "idle" : status} />
        <span className="mono dim bench-port" title={portLabel}>{portLabel}</span>
      </div>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={pickPort} disabled={status === "busy"}>
          {station.port ? "Re-pick port…" : "Connect port…"}
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={run}
          disabled={!station.port || status === "busy" || !props.productionRunId}
        >
          Program device
        </button>
        {status === "busy" ? (
          <button type="button" className="btn btn-danger btn-sm" onClick={abort}>
            Abort
          </button>
        ) : null}
        {runId ? (
          <Link className="val-link" to={`/production/flash-runs/${runId}`}>
            run #{runId}
          </Link>
        ) : null}
      </div>
      <div className="muted bench-step">
        {stepLabel}
        {progress !== null ? ` — ${progress}%` : ""}
      </div>
      {error ? <div className="banner-error">{error}</div> : null}
      <div className="flash-log mono">
        {log.map((row, i) => (
          <div key={i} className={`fl-${row.dir}`}>
            {row.dir === "tx" ? "→ " : row.dir === "rx" ? "← " : ""}
            {row.text}
          </div>
        ))}
        <div ref={logEnd} />
      </div>

      {prompt ? (
        <div className="modal-backdrop">
          <div className="card pad modal-card">
            <h2 className="card-title">{prompt.label}</h2>
            <PromptInput secret={prompt.secret} onSubmit={answerPrompt} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PromptInput({ secret, onSubmit }: { secret: boolean; onSubmit: (v: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="btn-row modal-actions">
      <input
        className="row-input mono"
        type={secret ? "password" : "text"}
        value={value}
        autoFocus
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmit(value);
        }}
      />
      <button type="button" className="btn" onClick={() => onSubmit("")}>
        Skip
      </button>
      <button type="button" className="btn btn-primary" onClick={() => onSubmit(value)}>
        OK
      </button>
    </div>
  );
}
