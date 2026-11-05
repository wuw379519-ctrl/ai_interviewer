/** Amplitude gate only: no speech, identity, emotion or content inference. */
export function rootMeanSquare(samples: Float32Array): number {
  if (!samples.length) return 0;
  let sum = 0;
  for (const sample of samples) { const value = Number.isFinite(sample) ? Math.max(-1, Math.min(1, sample)) : 0; sum += value * value; }
  return Math.sqrt(sum / samples.length);
}

export class PlaybackInterruptionGate {
  private since: number | null = null;
  private previous: number | null = null;
  private fired = false;
  constructor(private readonly startedAt: number) {}
  update(rms: number, now: number): boolean {
    if (this.fired) return false;
    if (!Number.isFinite(now) || !Number.isFinite(rms) || now - this.startedAt < 1200 || rms < 0.045 ||
      (this.previous !== null && (now < this.previous || now - this.previous > 100))) {
      this.since = null; this.previous = Number.isFinite(now) ? now : null; return false;
    }
    this.previous = now; this.since ??= now;
    if (now - this.since < 240) return false;
    this.fired = true; return true;
  }
}
