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
