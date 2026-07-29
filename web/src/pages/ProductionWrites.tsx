/** Write log — every write that moved money, each undoable, with row-level
 *  detail one click away. The undo path for applied JLC decisions lives here
 *  (their Clear buttons point at this page once applied). */
import WriteLog from "../components/invoices/WriteLog";

export default function ProductionWrites() {
  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Write log</h1>
          <span className="toolbar-total">
            reversing re-asserts the register against the state before the batch — not zero
          </span>
        </div>
        <WriteLog />
      </div>
    </div>
  );
}
