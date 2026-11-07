import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DependencyList,
  type Dispatch,
  type SetStateAction,
} from "react";
import { errorMessage, isAbortError } from "../api";

export interface LoadOptions {
  /** False: no fetch runs, and the hook clears the data unless `once` is on. */
  enabled?: boolean;
  /** Keep the old data when a dependency changes, so a table does not jump. */
  keep?: boolean;
  /** Fetch only until an answer is here, for a fold or a picker that opens many
   *  times. A dependency change or a new `enabled` does not fetch again. */
  once?: boolean;
}

export interface Load<T> {
  /** The last answer, or null before it. */
  data: T | null;
  setData: Dispatch<SetStateAction<T | null>>;
  error: string | null;
  setError: Dispatch<SetStateAction<string | null>>;
  /** True from the start of a fetch until it answers. */
  loading: boolean;
  /** Fetch again now. The data stays on screen, and a success clears the error. To
   *  blank the screen first, call `setData(null)`. It is stable, so it can go in the
   *  deps of another effect. It resolves when this fetch ends, and it never rejects. */
  reload: () => Promise<void>;
}

/** The answer of a fetch that runs on mount and on each change of `deps`.
 *
 *  A dependency change aborts the fetch in flight and clears the data and the error.
 *  An abort is not an error. An answer that arrives after an abort is dropped, so a
 *  stale answer never overwrites a newer one.
 *
 *  `load` runs inside the effect, so a reset of other state can go at its head and a
 *  filter can go in its `.then`. `deps` decides when it runs. `load` itself is not a
 *  dependency, so a caller writes it inline. */
export function useLoad<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
  { enabled = true, keep = false, once = false }: LoadOptions = {},
): Load<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);

  const latest = useRef(load);
  latest.current = load;
  const inFlight = useRef<AbortController | null>(null);
  /** False after unmount and while disabled: `reload` then does nothing. */
  const active = useRef(false);

  const run = useCallback(() => {
    inFlight.current?.abort();
    const ctrl = new AbortController();
    inFlight.current = ctrl;
    setLoading(true);
    return latest.current(ctrl.signal).then(
      (answer) => {
        if (ctrl.signal.aborted) return;
        setData(answer);
        setError(null);
        setLoading(false);
      },
      (err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (!isAbortError(err)) setError(errorMessage(err));
        setLoading(false);
      },
    );
  }, []);

  const reload = useCallback(() => (active.current ? run() : Promise.resolve()), [run]);

  useEffect(() => {
    active.current = enabled;
    if (enabled && !(once && data !== null)) {
      if (!keep) setData(null);
      setError(null);
      void run();
    } else {
      if (!once) {
        setData(null);
        setError(null);
      }
      setLoading(false);
    }
    return () => {
      active.current = false;
      inFlight.current?.abort();
    };
    // `deps` stands for `load`, which is new on each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);

  return { data, setData, error, setError, loading, reload };
}
