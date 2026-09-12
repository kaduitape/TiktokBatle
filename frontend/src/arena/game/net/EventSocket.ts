import { WS_BASE } from "../../../api/client";
import type { ArenaMessage } from "../../../types/events";

export class EventSocket {
  private ws: WebSocket | null = null;
  private sessionId: string;
  private onMessage: (msg: ArenaMessage) => void;
  private reconnectTimer: number | null = null;
  private closedByUser = false;

  constructor(sessionId: string, onMessage: (msg: ArenaMessage) => void) {
    this.sessionId = sessionId;
    this.onMessage = onMessage;
  }

  connect(): void {
    this.closedByUser = false;
    const url = `${WS_BASE}/ws/arena/${this.sessionId}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as ArenaMessage;
        this.onMessage(data);
      } catch (err) {
        console.error("bad ws message", err);
      }
    };

    this.ws.onclose = () => {
      if (!this.closedByUser) {
        this.reconnectTimer = window.setTimeout(() => this.connect(), 2000);
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
    if (this.ws) {
      // Detach first: the closing handshake can still deliver a buffered
      // message, and by then the scene that owns this socket is gone.
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.close();
      this.ws = null;
    }
  }
}
