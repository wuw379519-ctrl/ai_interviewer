import { expect, it } from "vitest";
import { PlaybackInterruptionGate, rootMeanSquare } from "./interruption";
it("仅计算本地电平，空输入与非有限值不形成虚假信号", () => {
  expect(rootMeanSquare(new Float32Array())).toBe(0);
  expect(rootMeanSquare(new Float32Array([NaN, Infinity, 0]))).toBe(0);
  expect(rootMeanSquare(new Float32Array([0.5, -0.5]))).toBe(0.5);
});
it("播报起始宽限、静音和短脉冲不打断，持续电平只触发一次", () => {
  const gate = new PlaybackInterruptionGate(0);
  for (let time = 0; time < 1200; time += 20) expect(gate.update(0.1, time)).toBe(false);
  expect(gate.update(0.1, 1200)).toBe(false); expect(gate.update(0.01, 1220)).toBe(false);
  for (let time = 1240; time < 1480; time += 20) expect(gate.update(0.1, time)).toBe(false);
  expect(gate.update(0.1, 1480)).toBe(true); expect(gate.update(0.1, 1500)).toBe(false);
});
it("后台调度间隔和时钟回退不拼接为持续发声", () => {
  const gate = new PlaybackInterruptionGate(0);
  expect(gate.update(0.1, 1200)).toBe(false); expect(gate.update(0.1, 1700)).toBe(false);
  expect(gate.update(0.1, 1600)).toBe(false); expect(gate.update(NaN, 1620)).toBe(false);
  for (let time = 1640; time < 1880; time += 20) expect(gate.update(0.1, time)).toBe(false);
  expect(gate.update(0.1, 1880)).toBe(true);
});
