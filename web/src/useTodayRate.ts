/** PLN per USD today, for a figure that belongs to no batch: the value of stock
 *  on a shelf, a planned price. Read once per page load: the rate moves once a day,
 *  and every figure on a screen must use the same one (decision 0103). */
import { useEffect, useState } from "react";
import { getFxAt } from "./api";

let cached: Promise<number | null> | null = null;

export function useTodayRate(): number | null {
  const [rate, setRate] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    cached ??= getFxAt("").then((r) => (r.rates.PLN ? 1 / r.rates.PLN : null));
    cached.then((v) => { if (live) setRate(v); }).catch(() => { cached = null; });
    return () => { live = false; };
  }, []);
  return rate;
}
