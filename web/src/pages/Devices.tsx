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
      // A SERIAL IS NEVER CUT. It is the MAC without separators — 12 characters,
      // always — and a truncated one is not an identity. A percent width made
      // that a promise about the window size: at 1280 the column fell to 105px
      // and clipped a 118px serial. This is a length, so the column is the
      // same 12 characters wide whatever the table does around it.
      width: "126px",
      serverFilter: true,
      className: "mono",
      get: (d) => d.serial || d.mac,
      render: (d) => (
        <Link className="comp-link" to={`/production/devices/${d.id}`}>
          {d.serial || d.mac}
        </Link>
      ),
    },
    { key: "mac", label: "MAC", width: 21, serverFilter: true, className: "mono dim", get: (d) => d.mac },
    { key: "chip", label: "Chip", width: 23, serverFilter: true, get: (d) => d.chip || "—" },
    // Four columns are deliberately absent (user decision 2026-09-16). NAME is
    // the serial with a `dongle_` prefix, and the search box above matches it.
    // PROJECT is the selector in the toolbar. IMEI is blank on every unit
    // without a modem. CHECKS said `4/4` beside a RESULT that already said
    // PASS — the device page is where what a run proved belongs. Each was
    // spending width on something the row already told you.
    // Batch lives on another table; the server joins it by name so it sorts
    // and filters like any other column.
    { key: "batch", label: "Batch", width: 20, serverFilter: true, get: (d) => d.batch?.label ?? "—" },
    {
      key: "state",
      label: "Where",
      width: 15,
      serverFilter: true,
      get: (d) => d.state || "",
      render: (d) => (d.state ? <StatusPill status={d.state} /> : <>—</>),
    },
    // Nothing below 6%: a filter box has a 60px floor (`input.filter-input`),
    // and a narrower column made it hang over its neighbour.
    { key: "runs", label: "Runs", width: 10, numeric: true, serverFilter: true, get: (d) => d.runs },
    {
      key: "last_status",
      label: "Result",
      width: 11,
      serverFilter: true,
      get: (d) => d.last_status ?? "",
      render: (d) => (d.last_status ? <StatusPill status={d.last_status} /> : <>—</>),
    },
    {
      // A timestamp is the other column that must never be cut: "2026-07-08 0…"
      // is not a time, and its length is as fixed as the serial's. Same
      // mechanism, same reason — a length, not a share of the window.
      key: "last_seen",
      label: "Last seen",
      width: "152px",
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
