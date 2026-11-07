/** What a crafted batch's page reads: the craft view, the cost by step, the
 *  assembly draft and the project's other batches. One load for the whole page,
 *  because the header figures, Floor, Devices and Money all read it.
 *
 *  It loads again when the window gets the focus: the bench works in another tab
 *  and changes these figures behind the page's back, and returning here is
 *  exactly when they are read.
 */
import { useCallback, useEffect, useState } from "react";
import {
  errorMessage,
  getAssemblyDraft,
  getCostByStep,
  getCraft,
  getRuns,
  isAbortError,
  type AssemblyDraft,
  type CostByStep,
  type CraftView,
  type RunInfo,
} from "../../api";

export interface Craft {
  view: CraftView | null;
  error: string | null;
  costs: CostByStep | null;
  draft: AssemblyDraft | null;
  draftError: string | null;
  runs: RunInfo[];
  reload: () => void;
}

export function useCraft(runId: number, projectId: number | null, crafted: boolean): Craft {
  const [view, setView] = useState<CraftView | null>(null);
  const [costs, setCosts] = useState<CostByStep | null>(null);
  const [draft, setDraft] = useState<AssemblyDraft | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    // An undone rebuild unpins the batch, so an old view must not stay on screen.
    if (!crafted) setView(null);
    if (!crafted || projectId === null) return;
    const ac = new AbortController();
    getCraft(runId, ac.signal)
      .then((v) => { setView(v); setError(null); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    getRuns(projectId, ac.signal).then(setRuns).catch(() => undefined);
    getCostByStep(runId, ac.signal).then(setCosts).catch(() => setCosts(null));
    // Its own error path: a draft that cannot be read breaks the assembly card,
    // not the rest of the page.
    getAssemblyDraft(runId, ac.signal)
      .then((d) => { setDraft(d); setDraftError(null); })
      .catch((err) => { if (!isAbortError(err)) { setDraft(null); setDraftError(errorMessage(err)); } });
    return () => ac.abort();
  }, [runId, projectId, crafted, tick]);

  useEffect(() => {
    if (!crafted) return;
    window.addEventListener("focus", reload);
    return () => window.removeEventListener("focus", reload);
  }, [crafted, reload]);

  return { view, error, costs, draft, draftError, runs, reload };
}
