/** What the bench says out loud when a device is finished (user request
 *  2026-10-24): one sound for PASS and another for FAIL, played once every
 *  selected step has ended — not per step, and not for an Abort, which the
 *  operator caused and is already looking at.
 *
 *  Synthesised with Web Audio, so there is no file to fetch and nothing to
 *  keep in step with a deploy. Chrome starts an AudioContext suspended until
 *  the page has had a click; a bench page always has (Run, Assign socket, the
 *  checkboxes), and before that the sound is simply skipped.
 */
let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

/** One note: frequency in Hz, start and length in seconds from now. */
function note(ac: AudioContext, freq: number, at: number, length: number, type: OscillatorType, peak: number) {
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  const t0 = ac.currentTime + at;
  gain.gain.setValueAtTime(0, t0);
  gain.gain.linearRampToValueAtTime(peak, t0 + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + length);
  osc.connect(gain).connect(ac.destination);
  osc.start(t0);
  osc.stop(t0 + length + 0.02);
}

/** PASS: two rising notes, short and clear (C6 then G6). FAIL: three low
 *  buzzes, so the two cannot be mistaken for each other across a room. */
export function playVerdict(verdict: "pass" | "fail") {
  const ac = audio();
  if (!ac) return;
  if (verdict === "pass") {
    note(ac, 1046.5, 0, 0.16, "sine", 0.25);
    note(ac, 1568.0, 0.14, 0.3, "sine", 0.25);
  } else {
    for (const at of [0, 0.22, 0.44]) note(ac, 196, at, 0.18, "square", 0.12);
  }
}
