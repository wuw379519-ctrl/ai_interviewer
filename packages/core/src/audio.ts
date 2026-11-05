/** Canonical mono 16kHz PCM WAV; contains audio samples only, no video container. */
export function encodePcmWave(samples: Float32Array): ArrayBuffer {
  if (samples.length === 0 || samples.length > 16000 * 120) throw new Error("音频必须在120秒以内");
  const buffer = new ArrayBuffer(44 + samples.length * 2), view = new DataView(buffer);
  const write = (offset: number, value: string) => { for (let index = 0; index < value.length; index++) view.setUint8(offset + index, value.charCodeAt(index)); };
  write(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); write(8, "WAVE"); write(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  write(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index++) {
    const value = samples[index] ?? 0, sample = Number.isFinite(value) ? Math.max(-1, Math.min(1, value)) : 0;
    view.setInt16(44 + index * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
  }
  return buffer;
}
