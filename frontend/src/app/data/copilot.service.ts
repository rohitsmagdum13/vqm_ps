import { Injectable, inject, signal } from '@angular/core';
import { AuthService } from '../core/auth/auth.service';
import { environment } from '../../environments/environment';
import type { CopilotMessage, CopilotMessageRole } from '../shared/models/triage';

interface ParsedSseEvent {
  readonly event: string;
  readonly data: string;
}

interface ToolCallPayload {
  readonly name?: string;
  readonly args?: Record<string, unknown>;
}

interface ToolResultPayload {
  readonly name?: string;
  readonly content?: string;
}

interface TextPayload {
  readonly content?: string;
  readonly message?: string;
}

function nowHHMMSS(): string {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => n.toString().padStart(2, '0'))
    .join(':');
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

/**
 * Parses a single SSE block (text between two blank-line delimiters)
 * into its event name and data payload. Returns null when the block
 * is empty or malformed.
 */
function parseSseBlock(block: string): ParsedSseEvent | null {
  let event = 'message';
  const dataLines: string[] = [];

  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (line.startsWith(':')) continue; // SSE comment
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join('\n') };
}

@Injectable({ providedIn: 'root' })
export class CopilotService {
  readonly #auth = inject(AuthService);

  readonly #threads = signal<Readonly<Record<string, readonly CopilotMessage[]>>>({});
  readonly #busy = signal<Readonly<Record<string, boolean>>>({});
  readonly #aborts = new Map<string, AbortController>();

  thread(queryId: string): readonly CopilotMessage[] {
    return this.#threads()[queryId] ?? [];
  }

  isBusy(queryId: string): boolean {
    return this.#busy()[queryId] === true;
  }

  reset(queryId: string): void {
    const ac = this.#aborts.get(queryId);
    if (ac) {
      ac.abort();
      this.#aborts.delete(queryId);
    }
    this.#threads.update((m) => ({ ...m, [queryId]: [] }));
    this.#busy.update((m) => ({ ...m, [queryId]: false }));
  }

  /**
   * Streams the reviewer copilot's response from the FastAPI backend.
   *
   * The backend opens an MCP session with the reviewer MCP server,
   * runs a LangGraph ReAct agent, and emits Server-Sent Events as the
   * agent calls tools and produces a final recommendation.
   */
  async ask(queryId: string, reviewerQuestion: string): Promise<void> {
    if (this.isBusy(queryId)) return;

    this.#append(queryId, { role: 'reviewer', content: reviewerQuestion });
    this.#busy.update((m) => ({ ...m, [queryId]: true }));

    const token = this.#auth.token();
    if (!token) {
      this.#append(queryId, {
        role: 'agent_final',
        content: 'Not signed in. Please log in again to use the copilot.',
      });
      this.#busy.update((m) => ({ ...m, [queryId]: false }));
      return;
    }

    const ac = new AbortController();
    this.#aborts.set(queryId, ac);

    try {
      const url = `${environment.apiBaseUrl}/copilot/triage/${encodeURIComponent(queryId)}/ask`;
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ question: reviewerQuestion }),
        signal: ac.signal,
      });

      if (!response.ok || !response.body) {
        const detail = await response.text().catch(() => `${response.status}`);
        this.#append(queryId, {
          role: 'agent_final',
          content: `Copilot request failed (${response.status}): ${detail.slice(0, 200)}`,
        });
        return;
      }

      await this.#consumeStream(queryId, response.body);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // User cleared / cancelled — silently swallow.
        return;
      }
      const message = err instanceof Error ? err.message : 'Unknown error';
      this.#append(queryId, {
        role: 'agent_final',
        content: `Copilot stream failed: ${message}`,
      });
    } finally {
      this.#aborts.delete(queryId);
      this.#busy.update((m) => ({ ...m, [queryId]: false }));
    }
  }

  /**
   * Reads the SSE response body chunk-by-chunk, splits on the blank-line
   * delimiter, and dispatches each event to #handleEvent.
   */
  async #consumeStream(queryId: string, body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE delimits events with a blank line. Process every complete
      // block we have so far and keep the trailing partial block.
      let delimIndex = buffer.indexOf('\n\n');
      while (delimIndex !== -1) {
        const block = buffer.slice(0, delimIndex);
        buffer = buffer.slice(delimIndex + 2);
        const parsed = parseSseBlock(block);
        if (parsed) this.#handleEvent(queryId, parsed);
        delimIndex = buffer.indexOf('\n\n');
      }
    }

    // Flush a final partial block if the server didn't terminate with \n\n.
    if (buffer.trim().length > 0) {
      const parsed = parseSseBlock(buffer);
      if (parsed) this.#handleEvent(queryId, parsed);
    }
  }

  /**
   * Translates one SSE event into a CopilotMessage and appends it to
   * the thread. Unknown events are ignored so future server-side
   * additions don't break the UI.
   */
  #handleEvent(queryId: string, evt: ParsedSseEvent): void {
    let payload: unknown;
    try {
      payload = JSON.parse(evt.data);
    } catch {
      // The 'done' event has data '{}' which parses fine; anything else
      // unparseable is treated as plain text.
      payload = { content: evt.data };
    }

    switch (evt.event) {
      case 'tool_call': {
        const p = payload as ToolCallPayload;
        this.#append(queryId, {
          role: 'tool_call',
          tool_name: p.name ?? '',
          tool_args: p.args ?? {},
          content: '',
        });
        return;
      }
      case 'tool_result': {
        const p = payload as ToolResultPayload;
        this.#append(queryId, {
          role: 'tool_result',
          tool_name: p.name ?? '',
          content: p.content ?? '',
        });
        return;
      }
      case 'final': {
        const p = payload as TextPayload;
        this.#append(queryId, { role: 'agent_final', content: p.content ?? '' });
        return;
      }
      case 'warning': {
        const p = payload as TextPayload;
        this.#append(queryId, {
          role: 'agent_thought',
          content: p.message ?? p.content ?? '',
        });
        return;
      }
      case 'error': {
        const p = payload as TextPayload;
        this.#append(queryId, {
          role: 'agent_final',
          content: `Error: ${p.message ?? p.content ?? 'Unknown error'}`,
        });
        return;
      }
      case 'done':
        // No-op; the finally block in ask() flips busy=false.
        return;
      default:
        // Forward unknown events as agent thoughts so they're at least
        // visible during dev rather than silently dropped.
        this.#append(queryId, {
          role: 'agent_thought' as CopilotMessageRole,
          content: `[${evt.event}] ${evt.data}`,
        });
    }
  }

  #append(queryId: string, msg: Omit<CopilotMessage, 'id' | 'timestamp'>): void {
    const full: CopilotMessage = { ...msg, id: uid(), timestamp: nowHHMMSS() };
    this.#threads.update((m) => ({
      ...m,
      [queryId]: [...(m[queryId] ?? []), full],
    }));
  }
}
