import type { Query, TierName, Vendor } from './models';
import type { VendorAccountDto } from '../services/vendors.api';

const TIER_MAP: Readonly<Record<string, TierName>> = {
  PLATINUM: 'PLATINUM',
  GOLD: 'GOLD',
  SILVER: 'SILVER',
  BRONZE: 'BRONZE',
};

/** Salesforce returns "Platinum"/"Gold"/etc. (mixed-case). Our UI uses
 * uppercase enum values. Anything unknown defaults to SILVER so the
 * tier badge never blows up rendering. */
function normalizeTier(raw: string | null | undefined): TierName {
  if (!raw) return 'SILVER';
  const upper = raw.toUpperCase();
  return TIER_MAP[upper] ?? 'SILVER';
}

/** SLA response & resolution windows aren't always populated in
 * Salesforce. Fall back to reasonable defaults per tier so the UI
 * doesn't show "0h / 0d" — those numbers would be misleading
 * for an account with no SLA set. */
function defaultSla(tier: TierName): { responseHours: number; resolutionDays: number } {
  switch (tier) {
    case 'PLATINUM':
      return { responseHours: 2, resolutionDays: 1 };
    case 'GOLD':
      return { responseHours: 4, resolutionDays: 3 };
    case 'SILVER':
      return { responseHours: 8, resolutionDays: 5 };
    case 'BRONZE':
      return { responseHours: 12, resolutionDays: 7 };
  }
}

/**
 * Compute the health score from local query data. Salesforce doesn't
 * expose this — it's a UI-only roll-up showing how many queries are
 * open and how many are P1. The formula is intentionally simple:
 * full health, minus 10 points per open P1 and 2 points per
 * open non-P1. Clamped to [40, 100].
 *
 * When real query metrics are wired in, this should be replaced
 * with a backend-computed value (e.g. from reporting.sla_metrics).
 */
function deriveHealth(openTotal: number, openP1: number): number {
  const raw = 100 - openP1 * 10 - Math.max(0, openTotal - openP1) * 2;
  return Math.max(40, Math.min(100, raw));
}

interface QueryStats {
  readonly openTotal: number;
  readonly openP1: number;
}

const OPEN_STATUSES = new Set<string>([
  'RECEIVED',
  'ANALYZING',
  'ROUTING',
  'DRAFTING',
  'VALIDATING',
  'AWAITING_RESOLUTION',
  'PAUSED',
  'DELIVERING',
  'REOPENED',
]);

function statsForVendor(vendorId: string, queries: readonly Query[]): QueryStats {
  let openTotal = 0;
  let openP1 = 0;
  for (const q of queries) {
    if (q.vendor_id !== vendorId) continue;
    if (!OPEN_STATUSES.has(q.status)) continue;
    openTotal += 1;
    if (q.priority === 'P1') openP1 += 1;
  }
  return { openTotal, openP1 };
}

/**
 * Convert a Salesforce VendorAccountData record into the UI Vendor
 * shape used by the design's screens. The mapper backfills three
 * UI-only fields (open_queries, p1_open, health) from the local
 * QUERIES array because the backend doesn't yet expose those metrics
 * — when a /vendors/{id}/metrics endpoint lands, swap the source.
 *
 * Also drops Salesforce records that have no `vendor_id` set: the
 * UI keys vendors by `V-XXX` everywhere, so a record with no code
 * can't safely render in lists, filters, or the command palette.
 */
export function toUiVendor(
  dto: VendorAccountDto,
  queries: readonly Query[],
): Vendor | null {
  if (!dto.vendor_id) return null;

  const tier = normalizeTier(dto.vendor_tier);
  const slaDefaults = defaultSla(tier);
  const stats = statsForVendor(dto.vendor_id, queries);

  return {
    vendor_id: dto.vendor_id,
    name: dto.name,
    website: dto.website ?? '',
    tier,
    category: dto.category ?? 'Uncategorized',
    payment_terms: dto.payment_terms ?? '—',
    annual_revenue: dto.annual_revenue ?? 0,
    sla_response_hours: dto.sla_response_hours ?? slaDefaults.responseHours,
    sla_resolution_days: dto.sla_resolution_days ?? slaDefaults.resolutionDays,
    status: (dto.vendor_status ?? 'ACTIVE').toUpperCase(),
    city: dto.billing_city ?? '—',
    state: dto.billing_state ?? '—',
    country: dto.billing_country ?? '—',
    onboarded_date: dto.onboarded_date ?? '—',
    health: deriveHealth(stats.openTotal, stats.openP1),
    open_queries: stats.openTotal,
    p1_open: stats.openP1,
  };
}

export function toUiVendors(
  dtos: readonly VendorAccountDto[],
  queries: readonly Query[],
): readonly Vendor[] {
  return dtos
    .map((d) => toUiVendor(d, queries))
    .filter((v): v is Vendor => v !== null);
}
