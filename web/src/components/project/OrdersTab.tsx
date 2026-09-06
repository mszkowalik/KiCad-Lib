/** Customer orders for this project's products — the demand side of the
 *  Batches tab. Read-only: an order is created and shipped from
 *  /production/orders, this tab only shows which orders want this project's
 *  devices and whether the shelf plus the planned batches cover them. */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  errorMessage,
  getDemand,
  isAbortError,
  listOrders,
  type DemandRow,
  type OrderLineRow,
  type OrderRow,
  type ProjectInfo,
} from "../../api";
import DataTable, { type Column } from "../DataTable";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { amount } from "../../format";
import { DemandCard } from "../../pages/Orders";

interface Props {
  project: ProjectInfo;
}

interface LineRow {
  key: string;
  order: OrderRow;
  line: OrderLineRow;
}

export default function OrdersTab({ project }: Props) {
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [demand, setDemand] = useState<DemandRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const ac = new AbortController();
    listOrders(ac.signal, project.id)
      .then((rows) => {
        setOrders(rows);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getDemand(project.id, ac.signal)
      .then(setDemand)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [project.id]);

  const rows = useMemo<LineRow[]>(
    () =>
      (orders ?? []).flatMap((o) =>
        o.lines
          .filter((l) => l.project_id === project.id)
          .map((l) => ({ key: `${o.id}:${l.id}`, order: o, line: l })),
      ),
    [orders, project.id],
  );

  const cols: Column<LineRow>[] = [
    { key: "date", label: "Date", width: 9, className: "mono", get: (r) => r.order.order_date },
    { key: "customer", label: "Customer", width: 14, get: (r) => r.order.customer },
    {
      key: "ref",
      label: "Reference",
      width: 15,
      className: "mono",
      get: (r) => r.order.order_ref || "—",
      render: (r) => (
        <Link className="comp-link" to={`/production/orders/${r.order.id}`} onClick={(e) => e.stopPropagation()}>
          {r.order.order_ref || `order #${r.order.id}`}
        </Link>
      ),
    },
    { key: "product", label: "Product", width: 14, get: (r) => r.line.product || r.line.project },
    { key: "ordered", label: "Ordered", width: 8, numeric: true, get: (r) => r.line.qty_ordered },
    { key: "shipped", label: "Shipped", width: 8, numeric: true, get: (r) => r.line.qty_shipped },
    {
      key: "open",
      label: "Open",
      width: 7,
      numeric: true,
      get: (r) => r.line.qty_open,
      render: (r) => <span className={r.line.qty_open ? "warn-text" : undefined}>{r.line.qty_open.toLocaleString()}</span>,
    },
    {
      key: "price",
      label: "Net unit price",
      width: 10,
      numeric: true,
      get: (r) => r.line.unit_price,
      render: (r) => <>{amount(r.line.unit_price, r.order.currency)}</>,
    },
    {
      key: "status",
      label: "Status",
      width: 8,
      get: (r) => r.order.status,
      render: (r) => <StatusPill status={r.order.status} />,
    },
  ];

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}
      <DemandCard rows={demand} title={`Demand for ${project.name}`} />
      <div className="card pad">
        <div className="toolbar">
          <h2 className="card-title">Customer orders</h2>
          <span className="toolbar-total">{orders ? `${rows.length} line(s)` : ""}</span>
          <Link className="btn btn-sm" to="/production/orders">
            All orders
          </Link>
        </div>
        <p className="card-subtitle">
          One row per order line for this project. Orders are created, invoiced and shipped
          from the Orders page.
        </p>
        {orders === null && !error ? <Spinner label="Loading orders" /> : null}
        {orders ? (
          <DataTable
            columns={cols}
            rows={rows}
            rowKey={(r) => r.key}
            persistKey="project-orders"
            defaultSort={{ key: "date", dir: "desc" }}
            onRowClick={(r) => navigate(`/production/orders/${r.order.id}`)}
            empty="No customer orders for this project yet."
          />
        ) : null}
      </div>
    </div>
  );
}
