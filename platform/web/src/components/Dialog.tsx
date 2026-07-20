/** Promise-based in-app dialogs replacing window.confirm / prompt / alert.
 *  Native browser popups are banned in this app — see CLAUDE.md. Mount
 *  <DialogProvider> once (App.tsx), then in any component:
 *
 *    const dialog = useDialog();
 *    if (!(await dialog.confirm("Delete this?", { tone: "danger" }))) return;
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

export interface ConfirmOptions {
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Confirm-button tone: "primary" (default), "danger" (destructive), "ok" (approve). */
  tone?: "primary" | "danger" | "ok";
}

export interface PromptOptions {
  title?: string;
  initial?: string;
  placeholder?: string;
  confirmLabel?: string;
}

export interface AlertOptions {
  title?: string;
}

export interface DialogApi {
  /** Resolves true if confirmed, false if cancelled/dismissed. */
  confirm: (message: string, opts?: ConfirmOptions) => Promise<boolean>;
  /** Resolves the entered text, or null if cancelled/dismissed. */
  prompt: (message: string, opts?: PromptOptions) => Promise<string | null>;
  /** Resolves once the user dismisses the message. */
  alert: (message: string, opts?: AlertOptions) => Promise<void>;
}

type Request =
  | { id: number; kind: "confirm"; message: string; opts: ConfirmOptions; resolve: (v: boolean) => void }
  | { id: number; kind: "prompt"; message: string; opts: PromptOptions; resolve: (v: string | null) => void }
  | { id: number; kind: "alert"; message: string; opts: AlertOptions; resolve: () => void };

const DialogContext = createContext<DialogApi | null>(null);

export function useDialog(): DialogApi {
  const api = useContext(DialogContext);
  if (api === null) throw new Error("useDialog must be used inside <DialogProvider>");
  return api;
}

const TONE_CLASS: Record<NonNullable<ConfirmOptions["tone"]>, string> = {
  primary: "btn-primary",
  danger: "btn-danger",
  ok: "btn-ok",
};

function DialogBox({ req, onDone }: { req: Request; onDone: () => void }) {
  const [value, setValue] = useState(req.kind === "prompt" ? (req.opts.initial ?? "") : "");
  const inputRef = useRef<HTMLInputElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (req.kind === "prompt") {
      inputRef.current?.focus();
      inputRef.current?.select();
    } else {
      primaryRef.current?.focus();
    }
  }, [req]);

  const cancel = () => {
    if (req.kind === "confirm") req.resolve(false);
    else if (req.kind === "prompt") req.resolve(null);
    else req.resolve();
    onDone();
  };

  const accept = () => {
    if (req.kind === "prompt" && !value.trim()) return;
    if (req.kind === "confirm") req.resolve(true);
    else if (req.kind === "prompt") req.resolve(value);
    else req.resolve();
    onDone();
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    accept();
  };

  const title =
    req.opts.title ??
    (req.kind === "confirm" ? "Confirm" : req.kind === "prompt" ? "Input needed" : "Notice");
  const confirmLabel =
    (req.kind !== "alert" ? req.opts.confirmLabel : undefined) ?? (req.kind === "alert" ? "OK" : "Confirm");
  const cancelLabel = (req.kind === "confirm" ? req.opts.cancelLabel : undefined) ?? "Cancel";
  const tone = req.kind === "confirm" ? (req.opts.tone ?? "primary") : "primary";

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) cancel();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          cancel();
        }
      }}
    >
      <div className="card pad modal-card" role="dialog" aria-modal="true" aria-label={title}>
        <div className="card-title">{title}</div>
        <p className="modal-msg">{req.message}</p>
        {req.kind === "prompt" ? (
          <form onSubmit={onSubmit}>
            <input
              ref={inputRef}
              type="text"
              className="text modal-input"
              value={value}
              placeholder={req.opts.placeholder}
              onChange={(e) => setValue(e.target.value)}
            />
          </form>
        ) : null}
        <div className="btn-row modal-actions">
          {req.kind !== "alert" ? (
            <button type="button" className="btn" onClick={cancel}>
              {cancelLabel}
            </button>
          ) : null}
          <button
            ref={primaryRef}
            type="button"
            className={`btn ${TONE_CLASS[tone]}`}
            disabled={req.kind === "prompt" && !value.trim()}
            onClick={accept}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function DialogProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<Request[]>([]);
  const nextId = useRef(1);

  const push = useCallback((req: Omit<Request, "id">) => {
    setQueue((q) => [...q, { ...req, id: nextId.current++ } as Request]);
  }, []);

  const api = useMemo<DialogApi>(
    () => ({
      confirm: (message, opts = {}) =>
        new Promise<boolean>((resolve) => push({ kind: "confirm", message, opts, resolve })),
      prompt: (message, opts = {}) =>
        new Promise<string | null>((resolve) => push({ kind: "prompt", message, opts, resolve })),
      alert: (message, opts = {}) =>
        new Promise<void>((resolve) => push({ kind: "alert", message, opts, resolve })),
    }),
    [push],
  );

  const current = queue[0];

  return (
    <DialogContext.Provider value={api}>
      {children}
      {current ? (
        <DialogBox key={current.id} req={current} onDone={() => setQueue((q) => q.slice(1))} />
      ) : null}
    </DialogContext.Provider>
  );
}
