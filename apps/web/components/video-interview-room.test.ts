import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  VideoInterviewRoom,
  captureVideoFrameBase64,
  shouldRequestMedia,
} from "./video-interview-room";

describe("VideoInterviewRoom helpers", () => {
  it("requests media only when enabled and no external stream", () => {
    expect(shouldRequestMedia(true, false)).toBe(true);
    expect(shouldRequestMedia(true, true)).toBe(false);
    expect(shouldRequestMedia(false, false)).toBe(false);
  });

  it("captures jpeg base64 from a mocked video/canvas", () => {
    const video = {
      videoWidth: 4,
      videoHeight: 3,
    } as HTMLVideoElement;
    const ctx = { drawImage: vi.fn() };
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ctx,
      toDataURL: () => "data:image/jpeg;base64,ZmFrZQ==",
    } as unknown as HTMLCanvasElement;
    const frame = captureVideoFrameBase64(video, canvas, 0.5);
    expect(frame).toBe("ZmFrZQ==");
    expect(canvas.width).toBe(4);
    expect(canvas.height).toBe(3);
    expect(ctx.drawImage).toHaveBeenCalled();
  });

  it("returns null when video has no dimensions", () => {
    const video = { videoWidth: 0, videoHeight: 0 } as HTMLVideoElement;
    const canvas = {
      getContext: () => ({ drawImage: vi.fn() }),
      toDataURL: () => "data:image/jpeg;base64,x",
    } as unknown as HTMLCanvasElement;
    expect(captureVideoFrameBase64(video, canvas)).toBeNull();
  });

  it("renders room chrome for SSR markup (permission/device wiring is client-only)", () => {
    const html = renderToStaticMarkup(
      createElement(VideoInterviewRoom, {
        interviewId: "00000000-0000-4000-8000-000000000099",
        token: "invite-token-fixture",
        enabled: false,
      }),
    );
    expect(html).toContain("视频语音面试");
    expect(html).toContain("avatar-stage");
    expect(html).toContain("self-preview");
  });
});
