/** Runs one solver job and reports its progress.
 *
 *  A solve is seconds to minutes, so it runs as a background job on the API and the
 *  page polls it. Two things the plain fetch pattern cannot do and this hook must:
 *  stream the design-frequency result before the sweep finishes (so the field appears
 *  early), and cancel — both when the user presses Cancel and when the component goes
 *  away, because an abandoned job holds a core and hundreds of megabytes.
 */
import { useCallback, useRef, useState } from "react";
import { fsCancelJob, fsJobFrames, fsJobPartial, fsJobStatus, fsStartJob, type FsFrame, type FsResult } from "../../api";

export interface Step {
  key: string;
  label: string;
}

export interface JobState {
  running: boolean;
  message: string;
  fraction: number;
  steps: Step[];
  current: number;
}

export interface RunOptions {
  steps?: Step[];
  onPartial?: (r: FsResult) => void;
  onFrame?: (f: FsFrame) => void;
}

const IDLE: JobState = { running: false, message: "", fraction: 0, steps: [], current: -1 };

export function useSolverJob() {
  const [state, setState] = useState<JobState>(IDLE);
  const idRef = useRef<string | null>(null);

  const cancel = useCallback(() => {
    const id = idRef.current;
    if (!id) return;
    setState((s) => ({ ...s, message: "cancelling…" }));
    fsCancelJob(id).catch(() => undefined);
  }, []);

  const run = useCallback(async <T,>(kind: string, payload: unknown, opts: RunOptions = {}): Promise<T | null> => {
    const steps = opts.steps ?? [];
    setState({ running: true, message: "queued", fraction: 0, steps, current: steps.length ? 0 : -1 });
    let id: string;
    try {
      ({ id } = await fsStartJob(kind, payload));
    } catch (err) {
      setState(IDLE);
      throw err;
    }
    idRef.current = id;
    let partialSeen = 0;
    let framesSeen = 0;
    try {
      for (;;) {
        await new Promise((r) => setTimeout(r, 350));
        const j = await fsJobStatus(id, true);
        setState((s) => ({
          ...s,
          message: j.message,
          fraction: j.fraction,
          current: j.phase ? Math.max(s.current, steps.findIndex((q) => q.key === j.phase)) : s.current,
        }));
        if (j.state === "running" && opts.onPartial && (j.partial_no ?? 0) > partialSeen) {
          partialSeen = j.partial_no ?? 0;
          try {
            opts.onPartial(await fsJobPartial(id));
          } catch {
            // the job may finish between the poll and the fetch; the full result follows
          }
        }
        if (j.state === "running" && opts.onFrame && (j.frames_f ?? []).length > framesSeen) {
          try {
            const fr = await fsJobFrames(id, framesSeen);
            framesSeen += fr.frames.length;
            fr.frames.forEach((f) => opts.onFrame?.(f));
          } catch {
            // same race as above
          }
        }
        if (j.state === "done") {
          if (opts.onFrame && (j.frames ?? []).length > framesSeen) {
            (j.frames ?? []).slice(framesSeen).forEach((f) => opts.onFrame?.(f));
          }
          return (j.result as T) ?? null;
        }
        if (j.state === "cancelled") return null;
        if (j.state === "error") throw new Error(j.error || "solver failed");
      }
    } finally {
      idRef.current = null;
      setState(IDLE);
    }
  }, []);

  return { state, run, cancel };
}
