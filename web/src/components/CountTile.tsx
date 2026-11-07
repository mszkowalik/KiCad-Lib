import type { ReactNode } from "react";

/** One figure and the label under it. A row of them goes in `.counts`, or in
 *  `.dash-tiles` on the Cost overview. */
export default function CountTile({ value, label, title, bad }: {
  value: ReactNode;
  label: ReactNode;
  /** How the figure is made, shown on the label. */
  title?: string;
  /** The figure is a fault, so it draws in the error colour. */
  bad?: boolean;
}) {
  return (
    <div className="count-tile">
      <div className={bad ? "v err-text" : "v"}>{value}</div>
      <div className="k" title={title}>{label}</div>
    </div>
  );
}
