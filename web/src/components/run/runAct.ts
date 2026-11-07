import { errorMessage } from "../../api";

/** A write from a panel of the batch page: busy while it runs, a failure in the
 *  panel's own error, and `after` once it has landed. */
export function runAct(
  setBusy: (busy: boolean) => void,
  setError: (message: string | null) => void,
  after: () => void,
) {
  return async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      after();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
}
