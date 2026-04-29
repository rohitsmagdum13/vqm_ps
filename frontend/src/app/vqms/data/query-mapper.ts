import type { Priority, ProcessingPath, Query, TierName, Vendor } from './models';
import type { AdminQueryDto } from '../services/queries.api';

/**
 * Backend uses LOW / MEDIUM / HIGH / CRITICAL on `portal_queries.priority`
 * (matches `models/query.py:Literal["LOW","MEDIUM","HIGH","CRITICAL"]`).
 * The UI uses P1 / P2 / P3 — collapse HIGH+CRITICAL into P1 because the
 * design treats both as the high-attention bucket.
 */
function normalizePriority(raw: string | null | undefined): Priority {
  if (!raw) return 'P3';
  const u = raw.toUpperCase();
  if (u === 'CRITICAL' || u === 'HIGH' || u === 'P1') return 'P1';
  if (u === 'MEDIUM' || u === 'P2') return 'P2';
  return 'P3';
}

function normalizePath(raw: string | null | undefined): ProcessingPath {
  if (raw === 'A' || raw === 'B' || raw === 'C') return raw;
  // Pre-routing rows (analysis still in flight) default to A — once
  // routing fires, the next /admin/queries refresh corrects it.
  return 'A';
}

function normalizeSource(raw: string | null | undefined): 'email' | 'portal' {
  return raw === 'portal' ? 'portal' : 'email';
}

interface SlaSnapshot {
  readonly pct: number | null;
  readonly minutesLeft: number | null;
}

/**
 * Translate `sla_deadline` (ISO string) into the % consumed and
 * minutes remaining that the SLA bar widget expects. Path A queries
 * have no SLA in the design, so a missing or past deadline returns
 * nulls and the SLA bar renders as "—".
 */
function computeSla(slaDeadline: string | null, createdAt: string): SlaSnapshot {
  if (!slaDeadline) return { pct: null, minutesLeft: null };
  const deadline = Date.parse(slaDeadline);
  const created = Date.parse(createdAt);
  if (Number.isNaN(deadline) || Number.isNaN(created)) {
    return { pct: null, minutesLeft: null };
  }
  const now = Date.now();
  const total = deadline - created;
  if (total <= 0) return { pct: 100, minutesLeft: 0 };
  const elapsed = now - created;
  const pct = Math.max(0, Math.min(100, Math.round((elapsed / total) * 100)));
  const minutesLeft = Math.max(0, Math.round((deadline - now) / 60_000));
  return { pct, minutesLeft };
}

const FALLBACK_TIER: TierName = 'SILVER';

/**
 * Translate one `AdminQueryDto` into the UI `Query` shape. The shell
 * fields the design expects (vendor_name, vendor_tier, intent, …) are
 * resolved from the supplied vendor lookup or fall back to placeholders
 * — the UI never breaks when a vendor record is missing or a query is
 * still pre-analysis.
 *
 * Several fields the design carries (correlation_id, execution_id,
 * confidence, kb_match, assigned_team, ticket_id, attachments,
 * reopened) are NOT in the `/admin/queries` listing payload. They stay
 * empty here and would be filled in either by `/admin/queries/{id}`
 * for a single-row drill-down or by future endpoints (analysis_result,
 * routing_decision, ticket_link).
 */
export function toUiQuery(
  dto: AdminQueryDto,
  resolveVendor: (id: string | null | undefined) => Vendor | null,
): Query {
  const vendor = resolveVendor(dto.vendor_id);
  const sla = computeSla(dto.sla_deadline, dto.created_at);
  const path = normalizePath(dto.processing_path);

  return {
    query_id: dto.query_id,
    correlation_id: '',
    execution_id: '',
    source: normalizeSource(dto.source),
    subject: dto.subject ?? '(no subject)',
    vendor_id: dto.vendor_id ?? 'UNRESOLVED',
    vendor_name: vendor?.name ?? (dto.vendor_id ?? 'Unknown vendor'),
    vendor_tier: vendor?.tier ?? FALLBACK_TIER,
    priority: normalizePriority(dto.priority),
    status: dto.status,
    processing_path: path,
    assigned_team: path === 'A' ? '—' : path === 'C' ? 'Triage Reviewer' : 'Unassigned',
    intent: dto.query_type ?? 'Uncategorized',
    confidence: 0, // filled by /admin/queries/{id} drill-down when wired
    kb_match: 0,
    received_at: dto.created_at,
    sla_pct: sla.pct,
    sla_deadline_min: sla.minutesLeft,
    attachments: 0,
    ticket_id: null,
    reopened: dto.status === 'REOPENED',
  };
}

export function toUiQueries(
  dtos: readonly AdminQueryDto[],
  resolveVendor: (id: string | null | undefined) => Vendor | null,
): readonly Query[] {
  return dtos.map((d) => toUiQuery(d, resolveVendor));
}
