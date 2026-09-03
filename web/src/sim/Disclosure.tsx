/** Reference material, closed until asked for.
 *
 *  The net list, the SPICE netlist, the control block and the off-sheet knobs
 *  are all things a person wants twice a day and never while reading a
 *  waveform. Open they pushed the circuit off the screen; behind a summary
 *  they cost one line each.
 */
export default function Disclosure({
  title, note, children, open,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
  open?: boolean;
}) {
  return (
    <details className="sim-details" open={open}>
      <summary>
        <span>{title}</span>
        {note ? <span className="muted">{note}</span> : null}
      </summary>
      <div className="sim-details-body">{children}</div>
    </details>
  );
}
