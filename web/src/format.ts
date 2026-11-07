/** Money formatters — the ONE place these live. Before this file there were
 *  eleven local copies across pages and panels, and they drifted: the AT COST
 *  column once rendered $102.128 because one copy forgot to clamp decimals. */

/** "$1,234.56" — a US-dollar amount with a $ prefix. */
export function usd(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return (
    "$" +
    v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  );
}

/** "1,234.56 PLN" — an amount in a named currency, always two decimals. */
export function amount(v: number | null | undefined, currency: string | null = "USD"): string {
  if (v == null) return "—";
  const s = v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${s} ${currency}` : s;
}

/** A stored USD figure in PLN (decision 0103). `rate` is the `pln_per_usd` of the
 *  figure's own batch, or `useTodayRate()` for a figure with no batch. With no rate
 *  it stays in USD: a real USD figure is better than a wrong PLN one. */
export function pln(v: number | null | undefined, rate: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return rate ? plnAmount(v * rate, digits) : usd(v, digits);
}

/** The same figure with no unit, for a narrow column whose header states the unit. */
export function plnNumber(v: number | null | undefined, rate: number | null | undefined, digits = 2): string {
  return plain(v == null ? v : v * (rate ?? 1), digits);
}

/** A figure the server already gives in PLN. */
export function plnAmount(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return `${v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} PLN`;
}

/** Unit prices: four decimals below 1 so a 0.0072 resistor stays visible,
 *  two above. Optional currency suffix. */
export function price(v: number | null | undefined, currency?: string | null): string {
  if (v == null) return "—";
  const digits = v < 1 && v > -1 ? 4 : 2;
  const s = v.toLocaleString(undefined, { maximumFractionDigits: digits });
  return currency ? `${s} ${currency}` : s;
}

/** "1,234.56" — a bare number with fixed decimals, no unit. */
export function plain(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** "1,234" — a whole number of pieces. */
export const qty = (v: number | null | undefined): string => plain(v, 0);

/** "1 position", "3 positions". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "1 234,56" — an amount as a Polish document prints it, for the figures read
 *  beside KSeF and the accountant's. Takes the API's decimal strings too. */
export function pl(v: string | number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A stored timestamp is UTC, and a screen shows the reader's local time (user,
 *  2026-11-07). A value with no zone is UTC too, or `new Date` would read it as
 *  local. A plain date has no time, so it does not convert: it stays that day. */
function parseStamp(iso: string): Date | null {
  const zoned = /[zZ]$|[+-]\d{2}(:?\d{2})?$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(zoned);
  return Number.isNaN(d.getTime()) ? null : d;
}

const isPlainDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s);
const pad2 = (n: number) => String(n).padStart(2, "0");
const ymd = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;

/** "2026-11-07", in the reader's time zone. */
export function localDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  if (isPlainDate(iso)) return iso;
  const d = parseStamp(iso);
  return d ? ymd(d) : iso;
}

/** "2026-11-07 17:30", in the reader's time zone. */
export function localWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  if (isPlainDate(iso)) return iso;
  const d = parseStamp(iso);
  return d ? `${ymd(d)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}` : iso;
}

/** "17:30:05", in the reader's time zone: a log line, where the seconds count. */
export function localTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = isPlainDate(iso) ? null : parseStamp(iso);
  return d ? `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}` : iso;
}

/** Today as YYYY-MM-DD in the LOCAL calendar. `toISOString()` is UTC, so
 *  between midnight and 02:00 in Poland it named yesterday. */
export function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/** How long ago, in one short word: "42s", "3 min", "5 h", "2 d". `null` when
 *  there is no time to count from, so each caller says what that means. */
export function since(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 90) return `${secs}s`;
  const mins = Math.round(secs / 60);
  if (mins < 90) return `${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} d`;
}
