/**
 * Candidate realtime WS client skeleton (Task 6a).
 * Audio pipeline / VAD / TTS playback land in Task 7b.
 *
 * Offline queue policy: messages are buffered while disconnected; on reconnect
 * they are flushed in order after auth+resume. Heartbeats are not queued.
 */
import {
  REALTIME_PROTOCOL_VERSION,
  type RealtimeClientMessage,
  type RealtimeServerMessage,
} from "@aii/core";

export type WsClientStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

export type InterviewWsClientOptions = {
  /** Absolute or same-origin ws(s)://…/ws/interview/{sessionId} */
  url: string;
  token: string;
  resumeFromSeq?: number;
  /** Max outbound messages kept while offline (default 32). Older drops first. */
  maxQueue?: number;
  onMessage?: (message: RealtimeServerMessage) => void;
  onStatus?: (status: WsClientStatus) => void;
};

export class InterviewWsClient {
  private socket: WebSocket | null = null;
  private status: WsClientStatus = "idle";
  private queue: RealtimeClientMessage[] = [];
  private resumeFromSeq: number;
  private readonly maxQueue: number;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private intentionallyClosed = false;
  /** Consecutive close-4000 (superseded) reconnects; reset on other closes (D74). */
  private supersedeAttempts = 0;

  constructor(private readonly options: InterviewWsClientOptions) {
    this.resumeFromSeq = options.resumeFromSeq ?? 0;
    this.maxQueue = options.maxQueue ?? 32;
  }

  connect(): void {
    this.intentionallyClosed = false;
    this.setStatus(this.status === "idle" || this.status === "closed" ? "connecting" : "reconnecting");
    const socket = new WebSocket(this.options.url);
    this.socket = socket;
    socket.addEventListener("open", () => {
      this.setStatus("open");
      this.sendNow({
        v: REALTIME_PROTOCOL_VERSION,
        type: "auth",
        token: this.options.token,
        resumeFromSeq: this.resumeFromSeq,
      });
      this.flushQueue();
      this.startHeartbeat();
    });
    socket.addEventListener("message", (event) => {
      if (typeof event.data !== "string") return;
      try {
        const parsed = JSON.parse(event.data) as RealtimeServerMessage;
        if (parsed.type === "ready" && typeof parsed.resumeFromSeq === "number") {
          this.resumeFromSeq = parsed.resumeFromSeq;
        }
        if (parsed.type === "event_replay" && Array.isArray(parsed.events)) {
          const last = parsed.events.at(-1);
          const seq = last && typeof last === "object" && last !== null && "seq" in last
            ? Number((last as { seq: unknown }).seq)
            : NaN;
          if (Number.isFinite(seq)) this.resumeFromSeq = seq;
        }
        this.options.onMessage?.(parsed);
      } catch {
        /* ignore malformed */
      }
    });
    socket.addEventListener("close", (event) => {
      this.stopHeartbeat();
      this.socket = null;
      if (!this.intentionallyClosed) {
        this.setStatus("reconnecting");
        // D74: 4000 = superseded — exponential backoff dampens multi-tab kick loops.
        let delayMs = 800;
        if (event.code === 4000) {
          this.supersedeAttempts += 1;
          delayMs = Math.min(8000, Math.round(1500 * 2 ** (this.supersedeAttempts - 1)));
        } else {
          this.supersedeAttempts = 0;
        }
        window.setTimeout(() => this.connect(), delayMs);
      } else {
        this.setStatus("closed");
      }
    });
  }

  /** Enqueue if not open; otherwise send immediately. Ping/close/proctor/video bypass the offline queue. */
  send(message: RealtimeClientMessage): void {
    if (
      message.type === "ping"
      || message.type === "close"
      || message.type === "auth"
      || message.type === "proctor_signal"
      || message.type === "video_chunk"
    ) {
      // High-rate video frames: drop while offline rather than ballooning the queue.
      this.sendNow(message);
      return;
    }
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.sendNow(message);
      return;
    }
    this.queue.push(message);
    while (this.queue.length > this.maxQueue) this.queue.shift();
  }

  close(reason?: string): void {
    this.intentionallyClosed = true;
    this.sendNow({ v: REALTIME_PROTOCOL_VERSION, type: "close", reason });
    this.socket?.close();
    this.stopHeartbeat();
    this.setStatus("closed");
  }

  private sendNow(message: RealtimeClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  private flushQueue(): void {
    const pending = this.queue.splice(0, this.queue.length);
    for (const message of pending) this.sendNow(message);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingTimer = setInterval(() => {
      this.sendNow({ v: REALTIME_PROTOCOL_VERSION, type: "ping", t: Date.now() });
    }, 15000);
  }

  private stopHeartbeat(): void {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  private setStatus(next: WsClientStatus): void {
    this.status = next;
    this.options.onStatus?.(next);
  }
}
