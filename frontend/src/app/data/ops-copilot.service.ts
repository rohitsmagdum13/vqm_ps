import { Injectable, signal } from '@angular/core';
import type { CopilotMessage } from '../shared/models/triage';
import { QUERY_STATUS_FIXTURES, SYSTEM_SNAPSHOT } from './ops.seed';

interface ScriptedStep {
  readonly delayMs: number;
  readonly message: Omit<CopilotMessage, 'id' | 'timestamp'>;
}

const THREAD_KEY = 'ops';

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
 * Mock copilot for the Admin / Ops Copilot. Routes to scripted responses
 * based on keywords in the question (DLQ, SLA, query lookup, cost, health,
 * path distribution). Real version connects to an MCP server with read-only
 * tools backed by CloudWatch / PostgreSQL / EventBridge.
 */
@Injectable({ providedIn: 'root' })
export class OpsCopilotService {
  readonly #thread = signal<readonly CopilotMessage[]>([]);
  readonly #busy = signal<boolean>(false);

  thread(): readonly CopilotMessage[] {
    return this.#thread();
  }

  isBusy(): boolean {
    return this.#busy();
  }

  reset(): void {
    this.#thread.set([]);
    this.#busy.set(false);
  }

  async ask(question: string): Promise<void> {
    if (this.isBusy()) return;

    this.#append({ role: 'reviewer', content: question });
    this.#busy.set(true);

    const script = this.#routeQuestion(question);
    for (const step of script) {
      await sleep(step.delayMs);
      this.#append(step.message);
    }

    this.#busy.set(false);
  }

  #append(msg: Omit<CopilotMessage, 'id' | 'timestamp'>): void {
    const full: CopilotMessage = { ...msg, id: uid(), timestamp: nowHHMMSS() };
    this.#thread.update((list) => [...list, full]);
  }

  #routeQuestion(question: string): readonly ScriptedStep[] {
    const q = question.toLowerCase();

    // VQ-YYYY-NNNN pattern → query status lookup
    const queryIdMatch = question.match(/VQ-\d{4}-\d{4}/i);
    if (queryIdMatch) {
      return this.#scriptForQueryStatus(queryIdMatch[0].toUpperCase());
    }
    if (q.includes('dlq') || q.includes('dead letter') || q.includes('queue depth')) {
      return this.#scriptForDlq();
    }
    if (q.includes('breach') || q.includes('sla')) {
      return this.#scriptForSla();
    }
    if (q.includes('cost') || q.includes('spend') || q.includes('llm')) {
      return this.#scriptForCost();
    }
    if (q.includes('health') || q.includes('status') || q.includes('latency') || q.includes('down')) {
      return this.#scriptForHealth();
    }
    if (q.includes('path') || q.includes('distribution')) {
      return this.#scriptForPathDistribution();
    }
    if (q.includes('stuck')) {
      return this.#scriptForStuck();
    }

    return this.#scriptForOverview();
  }

  // ─── DLQ ──────────────────────────────────────────────────────────────
  #scriptForDlq(): readonly ScriptedStep[] {
    const total = SYSTEM_SNAPSHOT.dlq.reduce((sum, q) => sum + q.depth, 0);
    const nonZero = SYSTEM_SNAPSHOT.dlq.filter((q) => q.depth > 0);
    const result = SYSTEM_SNAPSHOT.dlq.map((q) => `${q.queue_name}: ${q.depth}`).join(', ');

    return [
      {
        delayMs: 500,
        message: {
          role: 'agent_thought',
          content: 'Checking dead letter queue depths across all VQMS pipelines.',
        },
      },
      {
        delayMs: 600,
        message: {
          role: 'tool_call',
          tool_name: 'get_dlq_depth',
          tool_args: {},
          content: '',
        },
      },
      {
        delayMs: 700,
        message: { role: 'tool_result', tool_name: 'get_dlq_depth', content: result },
      },
      {
        delayMs: 800,
        message: {
          role: 'agent_final',
          content: total === 0
            ? `**All DLQs are empty.** No failed messages awaiting attention.`
            : `**Total DLQ depth: ${total}**\n\n`
              + nonZero.map((q) => `• \`${q.queue_name}\` — ${q.depth} message${q.depth === 1 ? '' : 's'}`).join('\n')
              + `\n\nAction: \`vqms-analysis-dlq\` has 2 stuck messages — likely Pydantic validation failures on AnalysisResult. Pull the messages and check for schema drift in recent prompt changes.`,
        },
      },
    ];
  }

  // ─── SLA ──────────────────────────────────────────────────────────────
  #scriptForSla(): readonly ScriptedStep[] {
    const sla = SYSTEM_SNAPSHOT.sla;
    return [
      {
        delayMs: 500,
        message: { role: 'agent_thought', content: 'Pulling SLA metrics for the last 24h window.' },
      },
      {
        delayMs: 600,
        message: {
          role: 'tool_call',
          tool_name: 'get_sla_breach_count',
          tool_args: { window: 'last_24h' },
          content: '',
        },
      },
      {
        delayMs: 700,
        message: {
          role: 'tool_result',
          tool_name: 'get_sla_breach_count',
          content:
            `total=${sla.total}, breached=${sla.breached}, warning=${sla.warning}, on_track=${sla.on_track}; `
            + `by_path: A=${sla.breaches_by_path.A}, B=${sla.breaches_by_path.B}, C=${sla.breaches_by_path.C}`,
        },
      },
      {
        delayMs: 800,
        message: {
          role: 'agent_final',
          content:
            `**SLA — last 24h**\n\n`
            + `• Total: ${sla.total}\n`
            + `• Breached: ${sla.breached} (${((sla.breached / sla.total) * 100).toFixed(1)}%)\n`
            + `• Warning (>70%): ${sla.warning}\n`
            + `• On track: ${sla.on_track}\n\n`
            + `Path B accounts for 2 of 3 breaches. Check open Path B tickets in Investigations — likely the LOGISTICS shipment delay tickets running long because they need carrier coordination.`,
        },
      },
    ];
  }

  // ─── Query lookup ─────────────────────────────────────────────────────
  #scriptForQueryStatus(queryId: string): readonly ScriptedStep[] {
    const fixture = QUERY_STATUS_FIXTURES.find((q) => q.query_id === queryId);
    if (!fixture) {
      return [
        {
          delayMs: 500,
          message: { role: 'agent_thought', content: `Looking up ${queryId} in workflow.case_execution.` },
        },
        {
          delayMs: 600,
          message: {
            role: 'tool_call',
            tool_name: 'get_query_status',
            tool_args: { query_id: queryId },
            content: '',
          },
        },
        {
          delayMs: 700,
          message: {
            role: 'tool_result',
            tool_name: 'get_query_status',
            content: `not_found: ${queryId}`,
          },
        },
        {
          delayMs: 600,
          message: {
            role: 'agent_final',
            content: `**${queryId} not found.** Either the ID is wrong or the row was archived. Check \`audit.action_log\` for any recent activity on this ID.`,
          },
        },
      ];
    }

    return [
      {
        delayMs: 500,
        message: { role: 'agent_thought', content: `Looking up ${queryId} in workflow.case_execution.` },
      },
      {
        delayMs: 600,
        message: {
          role: 'tool_call',
          tool_name: 'get_query_status',
          tool_args: { query_id: queryId },
          content: '',
        },
      },
      {
        delayMs: 750,
        message: {
          role: 'tool_result',
          tool_name: 'get_query_status',
          content:
            `status=${fixture.status}, node=${fixture.current_node}, path=${fixture.path}, `
            + `last_action_at=${fixture.last_action_at}, correlation_id=${fixture.correlation_id}`,
        },
      },
      {
        delayMs: 900,
        message: {
          role: 'agent_final',
          content:
            `**${queryId} — ${fixture.status}**\n\n`
            + `• Current node: \`${fixture.current_node}\`\n`
            + `• Path: ${fixture.path}\n`
            + `• Opened: ${fixture.opened_at}\n`
            + `• Last action: ${fixture.last_action} (${fixture.last_action_at})\n`
            + `• correlation_id: \`${fixture.correlation_id}\`\n\n`
            + (fixture.status === 'PAUSED_AWAITING_REVIEW'
              ? `This query is in **Path C** waiting for a reviewer. It is not stuck — review hasn't completed yet. Check the Triage queue.`
              : fixture.status === 'IN_PROGRESS'
              ? `Workflow is healthy and progressing. Last action ${this.#minutesAgo(fixture.last_action_at)} min ago.`
              : `No issue — completed.`),
        },
      },
    ];
  }

  // ─── Cost ─────────────────────────────────────────────────────────────
  #scriptForCost(): readonly ScriptedStep[] {
    const c = SYSTEM_SNAPSHOT.cost;
    const delta = c.today_usd - c.yesterday_usd;
    const deltaPct = ((delta / c.yesterday_usd) * 100).toFixed(1);
    return [
      {
        delayMs: 500,
        message: { role: 'agent_thought', content: 'Pulling LLM cost metrics for today and yesterday.' },
      },
      {
        delayMs: 600,
        message: {
          role: 'tool_call',
          tool_name: 'cost_today',
          tool_args: { include_breakdown: true },
          content: '',
        },
      },
      {
        delayMs: 750,
        message: {
          role: 'tool_result',
          tool_name: 'cost_today',
          content:
            `today=$${c.today_usd}, yesterday=$${c.yesterday_usd}, avg_per_query=$${c.avg_per_query_usd}; `
            + `breakdown: analysis=$${c.breakdown.analysis}, resolution=$${c.breakdown.resolution}, `
            + `acknowledgment=$${c.breakdown.acknowledgment}, embeddings=$${c.breakdown.embeddings}`,
        },
      },
      {
        delayMs: 800,
        message: {
          role: 'agent_final',
          content:
            `**LLM cost — today**\n\n`
            + `• Today: $${c.today_usd.toFixed(2)}\n`
            + `• Yesterday: $${c.yesterday_usd.toFixed(2)} (${delta < 0 ? '↓' : '↑'} ${Math.abs(parseFloat(deltaPct))}%)\n`
            + `• Avg per query: $${c.avg_per_query_usd.toFixed(3)}\n\n`
            + `**Breakdown**\n`
            + `• Analysis (LLM #1): $${c.breakdown.analysis.toFixed(2)} (${((c.breakdown.analysis / c.today_usd) * 100).toFixed(0)}%)\n`
            + `• Resolution (LLM #2): $${c.breakdown.resolution.toFixed(2)} (${((c.breakdown.resolution / c.today_usd) * 100).toFixed(0)}%)\n`
            + `• Acknowledgment: $${c.breakdown.acknowledgment.toFixed(2)}\n`
            + `• Embeddings (Titan v2): $${c.breakdown.embeddings.toFixed(2)}\n\n`
            + `Spend is down ${Math.abs(parseFloat(deltaPct))}% vs yesterday. Within the $0.50/query budget cap (current avg $0.131).`,
        },
      },
    ];
  }

  // ─── Health ───────────────────────────────────────────────────────────
  #scriptForHealth(): readonly ScriptedStep[] {
    const services = SYSTEM_SNAPSHOT.pipeline_health;
    const degraded = services.filter((s) => s.status !== 'healthy');
    return [
      {
        delayMs: 500,
        message: { role: 'agent_thought', content: 'Running pipeline health probe across all adapters.' },
      },
      {
        delayMs: 600,
        message: { role: 'tool_call', tool_name: 'pipeline_health', tool_args: {}, content: '' },
      },
      {
        delayMs: 800,
        message: {
          role: 'tool_result',
          tool_name: 'pipeline_health',
          content: services.map((s) => `${s.name}: ${s.status} (p99 ${s.latency_p99_ms}ms)`).join(', '),
        },
      },
      {
        delayMs: 900,
        message: {
          role: 'agent_final',
          content: degraded.length === 0
            ? `**All systems healthy.** ${services.length} services responding within latency targets.`
            : `**${degraded.length} service(s) degraded.**\n\n`
              + degraded.map((s) => `• **${s.name}** — ${s.status}, p99 ${s.latency_p99_ms}ms${s.note ? `\n  ${s.note}` : ''}`).join('\n')
              + `\n\nThe remaining ${services.length - degraded.length} services are healthy. No customer-facing impact yet because of caching, but monitor.`,
        },
      },
    ];
  }

  // ─── Path distribution ────────────────────────────────────────────────
  #scriptForPathDistribution(): readonly ScriptedStep[] {
    const p = SYSTEM_SNAPSHOT.path_distribution_today;
    const total = p.A + p.B + p.C;
    return [
      {
        delayMs: 500,
        message: { role: 'agent_thought', content: 'Pulling path distribution for today.' },
      },
      {
        delayMs: 600,
        message: {
          role: 'tool_call',
          tool_name: 'path_distribution',
          tool_args: { window: 'today' },
          content: '',
        },
      },
      {
        delayMs: 750,
        message: {
          role: 'tool_result',
          tool_name: 'path_distribution',
          content: `A=${p.A}, B=${p.B}, C=${p.C}, total=${total}`,
        },
      },
      {
        delayMs: 800,
        message: {
          role: 'agent_final',
          content:
            `**Path distribution — today (${total} queries)**\n\n`
            + `• Path A (AI-resolved): ${p.A} (${((p.A / total) * 100).toFixed(0)}%)\n`
            + `• Path B (team-resolved): ${p.B} (${((p.B / total) * 100).toFixed(0)}%)\n`
            + `• Path C (human review): ${p.C} (${((p.C / total) * 100).toFixed(0)}%)\n\n`
            + `Path A rate (${((p.A / total) * 100).toFixed(0)}%) is on target — KB coverage is doing its job. Path C rate (${((p.C / total) * 100).toFixed(0)}%) is slightly elevated; check whether new vendor onboarding spiked low-confidence queries.`,
        },
      },
    ];
  }

  // ─── Stuck queries ────────────────────────────────────────────────────
  #scriptForStuck(): readonly ScriptedStep[] {
    const stuck = SYSTEM_SNAPSHOT.stuck_queries;
    return [
      {
        delayMs: 500,
        message: { role: 'agent_thought', content: 'Looking for queries with no state transition in the last 10 minutes.' },
      },
      {
        delayMs: 600,
        message: {
          role: 'tool_call',
          tool_name: 'get_stuck_queries',
          tool_args: { idle_threshold_min: 10 },
          content: '',
        },
      },
      {
        delayMs: 750,
        message: {
          role: 'tool_result',
          tool_name: 'get_stuck_queries',
          content: stuck.length === 0 ? 'none' : stuck.map((s) => `${s.query_id} stuck at ${s.stuck_at_node} for ${s.stuck_for_min}min`).join('; '),
        },
      },
      {
        delayMs: 800,
        message: {
          role: 'agent_final',
          content: stuck.length === 0
            ? `**No stuck queries.** All in-progress queries have transitioned within the last 10 minutes.`
            : `**${stuck.length} stuck quer${stuck.length === 1 ? 'y' : 'ies'}**\n\n`
              + stuck.map((s) => `• \`${s.query_id}\` (${s.vendor}) — ${s.stuck_for_min}min at \`${s.stuck_at_node}\``).join('\n')
              + `\n\nFor \`VQ-2026-0123\`: stuck at \`context_loading\` likely because Salesforce p99 latency is elevated (4.8s). The vendor profile lookup is timing out before cache hit. Should self-recover when Salesforce stabilises.`,
        },
      },
    ];
  }

  // ─── Overview (default) ───────────────────────────────────────────────
  #scriptForOverview(): readonly ScriptedStep[] {
    const s = SYSTEM_SNAPSHOT;
    const totalDlq = s.dlq.reduce((sum, q) => sum + q.depth, 0);
    return [
      {
        delayMs: 500,
        message: { role: 'agent_thought', content: 'Building a quick system overview.' },
      },
      {
        delayMs: 600,
        message: { role: 'tool_call', tool_name: 'pipeline_health', tool_args: {}, content: '' },
      },
      {
        delayMs: 700,
        message: {
          role: 'tool_result',
          tool_name: 'pipeline_health',
          content: `${s.pipeline_health.filter((x) => x.status === 'healthy').length} healthy / ${s.pipeline_health.length} services`,
        },
      },
      {
        delayMs: 600,
        message: { role: 'tool_call', tool_name: 'get_dlq_depth', tool_args: {}, content: '' },
      },
      {
        delayMs: 700,
        message: { role: 'tool_result', tool_name: 'get_dlq_depth', content: `total=${totalDlq}` },
      },
      {
        delayMs: 800,
        message: {
          role: 'agent_final',
          content:
            `**System overview** (${s.timestamp_ist})\n\n`
            + `• Queries today: ${s.queries_today.received} received, ${s.queries_today.resolved} resolved, ${s.queries_today.in_progress} in progress\n`
            + `• DLQ depth: ${totalDlq} (mostly \`vqms-analysis-dlq\` — investigate)\n`
            + `• SLA breaches (last 24h): ${s.sla.breached} of ${s.sla.total}\n`
            + `• LLM cost today: $${s.cost.today_usd.toFixed(2)} (avg $${s.cost.avg_per_query_usd.toFixed(3)}/query)\n`
            + `• Pipeline: ${s.pipeline_health.filter((x) => x.status === 'healthy').length}/${s.pipeline_health.length} healthy (Salesforce degraded)\n\n`
            + `Ask me about any of these in detail, e.g. "why is VQ-2026-0123 stuck?" or "show me cost breakdown".`,
        },
      },
    ];
  }

  #minutesAgo(timestamp: string): number {
    const t = new Date(timestamp).getTime();
    const now = Date.now();
    return Math.max(0, Math.round((now - t) / 60000));
  }
}

export const OPS_THREAD_KEY = THREAD_KEY;
