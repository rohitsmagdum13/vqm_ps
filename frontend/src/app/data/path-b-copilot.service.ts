import { Injectable, inject, signal } from '@angular/core';
import type { CopilotMessage } from '../shared/models/triage';
import { PathBStore } from './path-b.store';

interface ScriptedStep {
  readonly delayMs: number;
  readonly message: Omit<CopilotMessage, 'id' | 'timestamp'>;
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

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Mock copilot for Path B investigation team. Simulates an MCP agent that
 * helps the team find facts and draft resolution notes.
 *
 * Real version connects to a FastMCP server with tools:
 *   - get_ticket_details
 *   - vendor_payment_history
 *   - related_kb_articles
 *   - search_internal_docs
 *   - draft_resolution_notes
 */
@Injectable({ providedIn: 'root' })
export class PathBCopilotService {
  readonly #store = inject(PathBStore);

  readonly #threads = signal<Readonly<Record<string, readonly CopilotMessage[]>>>({});
  readonly #busy = signal<Readonly<Record<string, boolean>>>({});
  readonly #drafts = signal<Readonly<Record<string, string>>>({});

  thread(ticketId: string): readonly CopilotMessage[] {
    return this.#threads()[ticketId] ?? [];
  }

  isBusy(ticketId: string): boolean {
    return this.#busy()[ticketId] === true;
  }

  /** Latest draft notes the agent suggested — team can copy into the editor. */
  latestDraft(ticketId: string): string {
    return this.#drafts()[ticketId] ?? '';
  }

  reset(ticketId: string): void {
    this.#threads.update((m) => ({ ...m, [ticketId]: [] }));
    this.#busy.update((m) => ({ ...m, [ticketId]: false }));
    this.#drafts.update((m) => ({ ...m, [ticketId]: '' }));
  }

  async ask(ticketId: string, question: string): Promise<void> {
    if (this.isBusy(ticketId)) return;

    this.#append(ticketId, { role: 'reviewer', content: question });

    const ticket = this.#store.byId(ticketId);
    if (!ticket) {
      this.#append(ticketId, {
        role: 'agent_final',
        content: `Ticket ${ticketId} not found.`,
      });
      return;
    }

    this.#busy.update((m) => ({ ...m, [ticketId]: true }));

    const script = this.#scriptFor(ticket);
    for (const step of script) {
      await sleep(step.delayMs);
      this.#append(ticketId, step.message);
    }

    // The final message contains a draft the team can copy into resolution notes.
    const finalMsg = script[script.length - 1].message;
    if (finalMsg.role === 'agent_final') {
      this.#drafts.update((m) => ({ ...m, [ticketId]: this.#extractDraft(finalMsg.content) }));
    }

    this.#busy.update((m) => ({ ...m, [ticketId]: false }));
  }

  #append(ticketId: string, msg: Omit<CopilotMessage, 'id' | 'timestamp'>): void {
    const full: CopilotMessage = { ...msg, id: uid(), timestamp: nowHHMMSS() };
    this.#threads.update((m) => ({
      ...m,
      [ticketId]: [...(m[ticketId] ?? []), full],
    }));
  }

  #scriptFor(ticket: { ticket_id: string; query_id: string; team: string; vendor: { vendor_id: string }; related_invoices: readonly string[]; related_pos: readonly string[]; ai_intent: string }): readonly ScriptedStep[] {
    const draft = this.#draftFor(ticket);

    return [
      {
        delayMs: 600,
        message: {
          role: 'agent_thought',
          content:
            'Investigating this ticket. I will pull the ticket details, related context, and KB articles.',
        },
      },
      {
        delayMs: 700,
        message: {
          role: 'tool_call',
          tool_name: 'get_ticket_details',
          tool_args: { ticket_id: ticket.ticket_id },
          content: '',
        },
      },
      {
        delayMs: 800,
        message: {
          role: 'tool_result',
          tool_name: 'get_ticket_details',
          content:
            `ticket=${ticket.ticket_id}, query=${ticket.query_id}, team=${ticket.team}, intent=${ticket.ai_intent}, `
            + `invoices=[${ticket.related_invoices.join(', ') || 'none'}], pos=[${ticket.related_pos.join(', ') || 'none'}]`,
        },
      },
      ...this.#teamSpecificSteps(ticket),
      {
        delayMs: 700,
        message: {
          role: 'tool_call',
          tool_name: 'related_kb_articles',
          tool_args: { intent: ticket.ai_intent, top_k: 3 },
          content: '',
        },
      },
      {
        delayMs: 800,
        message: {
          role: 'tool_result',
          tool_name: 'related_kb_articles',
          content: this.#kbResultsFor(ticket.ai_intent),
        },
      },
      {
        delayMs: 600,
        message: {
          role: 'agent_thought',
          content: 'I have enough context. Drafting suggested resolution notes for the team.',
        },
      },
      {
        delayMs: 700,
        message: {
          role: 'tool_call',
          tool_name: 'draft_resolution_notes',
          tool_args: { ticket_id: ticket.ticket_id, intent: ticket.ai_intent },
          content: '',
        },
      },
      {
        delayMs: 1000,
        message: {
          role: 'agent_final',
          content: draft,
        },
      },
    ];
  }

  #teamSpecificSteps(ticket: { team: string; vendor: { vendor_id: string }; related_invoices: readonly string[] }): readonly ScriptedStep[] {
    if (ticket.team === 'AP-FINANCE') {
      return [
        {
          delayMs: 700,
          message: {
            role: 'tool_call',
            tool_name: 'vendor_payment_history',
            tool_args: { vendor_id: ticket.vendor.vendor_id, last_n: 6 },
            content: '',
          },
        },
        {
          delayMs: 900,
          message: {
            role: 'tool_result',
            tool_name: 'vendor_payment_history',
            content:
              `Last 6 invoices: 5 paid on time, 1 disputed (INV-7741, resolved). `
              + `Vendor on NET-30 terms. Average invoice $42K. Current month spend $185K.`,
          },
        },
      ];
    }
    if (ticket.team === 'LOGISTICS') {
      return [
        {
          delayMs: 700,
          message: {
            role: 'tool_call',
            tool_name: 'search_internal_docs',
            tool_args: { query: 'shipment delay protocol Mumbai hub' },
            content: '',
          },
        },
        {
          delayMs: 900,
          message: {
            role: 'tool_result',
            tool_name: 'search_internal_docs',
            content:
              'Found Logistics SOP-007: Delay protocol requires (1) carrier root cause, '
              + '(2) updated ETA, (3) compensation review per contract Section 7.3.',
          },
        },
      ];
    }
    if (ticket.team === 'PROCUREMENT') {
      return [
        {
          delayMs: 700,
          message: {
            role: 'tool_call',
            tool_name: 'search_internal_docs',
            tool_args: { query: 'contract renewal escalation cap clause 12.4' },
            content: '',
          },
        },
        {
          delayMs: 900,
          message: {
            role: 'tool_result',
            tool_name: 'search_internal_docs',
            content:
              'Legal interpretation memo (March 2026): Clause 12.4 escalation cap is per-year, '
              + 'not cumulative. Confirmed by GC.',
          },
        },
      ];
    }
    return [
      {
        delayMs: 700,
        message: {
          role: 'tool_call',
          tool_name: 'search_internal_docs',
          tool_args: { query: ticket.team },
          content: '',
        },
      },
      {
        delayMs: 800,
        message: {
          role: 'tool_result',
          tool_name: 'search_internal_docs',
          content: 'Found 3 relevant SOPs for this team. See related_kb_articles for vendor-facing version.',
        },
      },
    ];
  }

  #kbResultsFor(intent: string): string {
    switch (intent) {
      case 'invoice_dispute':
        return 'KB-102 (Disputing an Invoice Amount, 0.91), KB-101 (Invoice Payment Status, 0.78)';
      case 'delivery_delay':
        return 'KB-301 (Delivery Delay Reporting, 0.94), KB-302 (Carrier Compensation, 0.71)';
      case 'contract_query':
        return 'KB-202 (Contract Renewal Timelines, 0.88), KB-203 (Price Escalation Rules, 0.85)';
      case 'compliance_query':
        return 'KB-401 (Annual Compliance Re-certification, 0.92), KB-402 (Audit Process, 0.79)';
      default:
        return 'No high-confidence KB matches found.';
    }
  }

  #draftFor(ticket: { ticket_id: string; query_id: string; ai_intent: string; related_invoices: readonly string[]; related_pos: readonly string[] }): string {
    const lines: string[] = [`**Suggested resolution notes for ${ticket.ticket_id}**`, ''];

    switch (ticket.ai_intent) {
      case 'invoice_dispute':
        lines.push(
          `Investigation findings:`,
          `• Reviewed ${ticket.related_invoices.join(', ')} against ${ticket.related_pos.join(', ')}.`,
          `• Line item "Q1 service adjustment $4,200" was an approved change order (CO-104) signed Mar 28.`,
          `• Charge is valid; CO-104 was missed on the invoice cover sheet.`,
          ``,
          `Resolution:`,
          `• Confirm CO-104 reference to vendor.`,
          `• Reissue invoice with CO-104 line item explicitly labelled.`,
          `• Vendor payment to follow standard NET-30 once reissued.`,
        );
        break;
      case 'delivery_delay':
        lines.push(
          `Investigation findings:`,
          `• Carrier confirmed truck breakdown at Mumbai hub.`,
          `• Replacement truck dispatched April 25 06:00.`,
          `• New ETA: April 26 noon.`,
          ``,
          `Resolution:`,
          `• Notify vendor of new ETA and root cause.`,
          `• Apply 2% compensation per contract Section 7.3 (delay > 48h).`,
          `• Add tracking link for the replacement shipment.`,
        );
        break;
      case 'contract_query':
        lines.push(
          `Investigation findings:`,
          `• Reviewed clause 12.4 with legal team.`,
          `• Cap is 5% per year, NOT cumulative across the renewal term.`,
          `• Aligns with March 2026 legal interpretation memo.`,
          ``,
          `Resolution:`,
          `• Send vendor written confirmation of per-year interpretation.`,
          `• Offer call with procurement lead if vendor wants to discuss renewal terms.`,
        );
        break;
      case 'compliance_query':
        lines.push(
          `Investigation findings:`,
          `• ISO 27001 certificate expiring May 30. Standard renewal applies.`,
          ``,
          `Resolution:`,
          `• Send vendor the renewal package: auditor contacts, document checklist, timeline.`,
          `• Audit kickoff May 10, certificate issuance by May 25.`,
          `• Confirm vendor has booked their internal audit slot.`,
        );
        break;
      default:
        lines.push(
          `Investigation findings:`,
          `• Reviewed ticket context and related documents.`,
          ``,
          `Resolution:`,
          `• Provide vendor with standard response based on KB articles.`,
        );
    }

    lines.push('', '_You can copy these notes into the editor and edit before submitting._');
    return lines.join('\n');
  }

  #extractDraft(content: string): string {
    // Extract the actual notes (skip the header and the "you can copy" footer).
    const lines = content.split('\n');
    const start = lines.findIndex((l) => l.startsWith('Investigation findings'));
    const end = lines.findIndex((l) => l.startsWith('_You can copy'));
    if (start === -1) return '';
    const slice = end === -1 ? lines.slice(start) : lines.slice(start, end);
    return slice.join('\n').trim();
  }
}
