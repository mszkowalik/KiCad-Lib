/** Produced devices — physical reality, keyed by the ESP MAC. Every unit the
 *  flasher ever touched, with batch, identity and programming history.
 *
 *  This is the platform's one SERVER-PAGED list: 5502 rows serialise to 1.98 MB
 *  and took 2.5 s to fetch (measured 2026-08-24), which no amount of clever
 *  rendering improves. So the page holds a window, and sorting and filtering
 *  are the server's job — a browser holding 100 of 5502 rows cannot honestly
 *  answer "no rows match". */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getProjects,
  isAbortError,
  listDevices,
  type DeviceListRow,
  type ProjectInfo,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { useInfiniteScroll } from "../components/useInfiniteScroll";
import { CheckBar } from "../components/flasher/CheckGrid";
import { fmtWhen } from "../components/flasher/common";
import { useStickyState } from "../useStickyState";

const PAGE = 100;
const DEBOUNCE_MS = 250;

export default function Devices() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [rows, setRows] = useState<DeviceListRow[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("devices.project", null);
  const [status, setStatus] = useStickyState<string>("devices.status", "");
  const [q, setQ] = useState("");

  // Column filters and sort, both applied server-side. `typed` debounces so a
  // keystroke is not a query.
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [columns, setColumns] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({
    key: "last_seen",
    dir: "desc",
  });

  useEffect(() => {
    const ac = new AbortController();
    getProjects(ac.signal)
      .then(setProjects)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  useEffect(() => {
    const t = window.setTimeout(() => setColumns(typed), DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [typed]);

  const query = useCallback(
    (offset: number, signal?: AbortSignal) =>
      listDevices(
        {
          project_id: projectId ?? undefined,
          status: status || undefined,
          q: q || undefined,
          columns,
          sort: sort.key,
          dir: sort.dir,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [projectId, status, q, columns, sort],
  );

  // Any filter or sort change is a different list: reset to the first page, or
  // the new rows would be appended under stale ones.
  const reqId = useRef(0);
  useEffect(() => {
    const ac = new AbortController();
    const mine = ++reqId.current;
    setBusy(true);
    setError(null);
    const t = window.setTimeout(() => {
      query(0, ac.signal)
        .then((page) => {
          if (mine !== reqId.current) return;
          setRows(page.items);
          setTotal(page.total);
          setHasMore(page.has_more);
          setBusy(false);
        })
        .catch((err) => {
          if (isAbortError(err) || mine !== reqId.current) return;
          setError(errorMessage(err));
          setBusy(false);
        });
    }, q ? DEBOUNCE_MS : 0);
    return () => {
      window.clearTimeout(t);
      ac.abort();
    };
  }, [query, q]);

  const loadMore = useCallback(() => {
    if (busy || !hasMore) return;
    const mine = reqId.current;
    setBusy(true);
    query(rows.length)
      .then((page) => {
        if (mine !== reqId.current) return;
        setRows((prev) => [...prev, ...page.items]);
        setTotal(page.total);
        setHasMore(page.has_more);
        setBusy(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(errorMessage(err));
        setBusy(false);
      });
  }, [busy, hasMore, query, rows.length]);

  const sentinel = useInfiniteScroll(loadMore, hasMore, busy);

  const cols: Column<DeviceListRow>[] = [
    {
      key: "serial",
      label: "Serial",
      width: 11,
      serverFilter: true,
      className: "mono",
      get: (d) => d.serial || d.mac,
      render: (d) => (
        <Link className="comp-link" to={`/production/devices/${d.id}`}>
          {d.serial || d.mac}
        </Link>
      ),
    },
    {
      key: "tasmota_id",
      label: "Name",
      width: 12,
      serverFilter: true,
      className: "mono dim",
      get: (d) => d.tasmota_id || "—",
    },
    { key: "mac", label: "MAC", width: 12, serverFilter: true, className: "mono dim", get: (d) => d.mac },
    { key: "chip", label: "Chip", width: 7, serverFilter: true, get: (d) => d.chip || "—" },
    // Project and batch live on other tables — the toolbar's project select is
    // the server-side control for the first, so neither takes a filter box.
    { key: "project", label: "Project", width: 10, interactive: false, get: (d) => d.project.name },
    { key: "batch", label: "Batch", width: 11, interactive: false, get: (d) => d.batch?.label ?? "—" },
    { key: "imei", label: "IMEI", width: 12, serverFilter: true, className: "mono dim", get: (d) => d.imei || "—" },
    { key: "runs", label: "Runs", width: 4, numeric: true, interactive: false, get: (d) => d.runs },
    {
      key: "checks",
      label: "Checks",
      width: 7,
      interactive: false,
      get: (d) => `${d.checks.pass}/${d.checks.fail}`,
      render: (d) => <CheckBar checks={d.checks} />,
    },
    {
      key: "last_status",
      label: "Last result",
      width: 7,
      serverFilter: true,
      get: (d) => d.last_status ?? "",
      render: (d) => (d.last_status ? <StatusPill status={d.last_status} /> : <>—</>),
    },
    {
      key: "last_seen",
      label: "Last seen",
      width: 8,
      className: "muted",
      get: (d) => d.last_seen ?? "",
      render: (d) => <>{fmtWhen(d.last_seen)}</>,
    },
  ];

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Devices</h1>
          <select
            className="row-input"
            value={projectId ?? ""}
            onChange={(e) => setProjectId(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">all projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <select className="row-input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">any result</option>
            <option value="pass">pass</option>
            <option value="fail">fail</option>
            <option value="aborted">aborted</option>
          </select>
          <input
            className="search"
            placeholder="MAC / serial / name / IMEI / ICCID…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span className="toolbar-total">
            {rows.length === total ? `${total} devices` : `${rows.length} of ${total} devices`}
          </span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="card">
          <div className="table-wrap">
            <DataTable
              columns={cols}
              rows={rows}
              rowKey={(d) => d.id}
              serverSort
              defaultSort={{ key: "last_seen", dir: "desc" }}
              onSortChange={(s) => setSort(s ?? { key: "last_seen", dir: "desc" })}
              onServerFilters={setTyped}
              pageSize={10000} // the server page IS the chunk
              empty={
                busy
                  ? "Loading…"
                  : "No devices recorded yet — they appear the moment a programming run reads a MAC."
              }
              footer={
                hasMore ? (
                  <div ref={sentinel} className="scroll-sentinel">
                    <Spinner label={`${rows.length} of ${total}`} />
                  </div>
                ) : null
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}
