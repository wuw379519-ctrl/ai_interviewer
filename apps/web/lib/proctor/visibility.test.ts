import { afterEach, describe, expect, it, vi } from "vitest";
import { attachVisibilityProctor, measureAnswerLatency } from "./visibility";

describe("proctor visibility", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("emits tab_hidden when document becomes hidden", () => {
    const listeners = new Map<string, EventListener>();
    const doc = {
      visibilityState: "visible" as string,
      addEventListener: (type: string, handler: EventListener) => {
        listeners.set(type, handler);
      },
      removeEventListener: (type: string) => {
        listeners.delete(type);
      },
      dispatchEvent: (event: Event) => {
        listeners.get(event.type)?.(event);
        return true;
      },
    };
    const win = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal("document", doc);
    vi.stubGlobal("window", win);

    const emit = vi.fn();
    const dispose = attachVisibilityProctor(emit);
    doc.visibilityState = "hidden";
    doc.dispatchEvent(new Event("visibilitychange"));
    expect(emit).toHaveBeenCalledWith({ signalType: "tab_hidden", payload: { hidden: true } });
    dispose();
  });

  it("measures answer latency from question shown", () => {
    expect(measureAnswerLatency(1000, 4500)).toBe(3500);
    expect(measureAnswerLatency(5000, 4000)).toBe(0);
  });
});
