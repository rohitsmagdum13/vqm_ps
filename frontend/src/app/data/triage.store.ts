import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import type {
  ConfidenceBreakdown,
  ReviewerDecision,
  TriageCase,
  TriageStatus,
  TriageVendor,
} from '../shared/models/triage';
import type { Vendor } from '../shared/models/vendor';
import {
  TriageApiService,
  type ConfidenceBreakdownDto,
  type TriagePackageDto,
  type TriageQueueItemDto,
} from './triage-api.service';
import { VendorService } from './vendor.service';

/**
 * The vendor management endpoints store tier as 'PLATINUM' | 'GOLD' |
 * 'SILVER' | 'BRONZE'. The triage UI was written against title-case
 * 'Platinum' | 'Gold' | …. This is the smallest mapping that keeps
 * both consumers happy without bigger refactors.
 */
function mapTier(t: string | null | undefined): TriageVendor['tier'] {
  switch ((t ?? '').toUpperCase()) {
    case 'PLATINUM':
      return 'Platinum';
    case 'GOLD':
      return 'Gold';
    case 'SILVER':
      return 'Silver';
    case 'BRONZE':
      return 'Bronze';
    default:
      return null;
  }
}

/**
 * Backend `status` values are PENDING / IN_REVIEW / COMPLETED.
 * Frontend uses PENDING_REVIEW (matches the existing components and
 * tab labels). Map at the boundary so neither side has to change.
 */
function mapStatus(backendStatus: string): TriageStatus {
  if (backendStatus === 'IN_REVIEW') return 'IN_REVIEW';
  if (backendStatus === 'COMPLETED' || backendStatus === 'REVIEWED') return 'COMPLETED';
  return 'PENDING_REVIEW';
}

function emptyBreakdown(): ConfidenceBreakdown {
  return {
    overall: 0,
    intent_classification: 0,
    entity_extraction: 0,
    single_issue_detection: 0,
    threshold: 0.85,
  };
}

function normaliseBreakdown(b?: ConfidenceBreakdownDto | null): ConfidenceBreakdown {
  if (!b) return emptyBreakdown();
  return {
    overall: b.overall ?? 0,
    intent_classification: b.intent_classification ?? 0,
    entity_extraction: b.entity_extraction ?? 0,
    single_issue_detection: b.single_issue_detection ?? 0,
    threshold: b.threshold ?? 0.85,
  };
}

/**
 * Build a TriageCase from a queue summary item. The detail fields
 * (subject, body, full analysis_result, breakdown) are placeholders
 * until loadPackage() is called for that query_id.
 */
function fromQueueItem(item: TriageQueueItemDto): TriageCase {
  const vendor: TriageVendor = { vendor_id: item.vendor_id ?? '—' };
  return {
    query_id: item.query_id,
    received_at: item.created_at,
    subject: item.subject ?? '(no subject)',
    body: '',
    vendor,
    status: mapStatus(item.status),

    ai_intent: item.ai_intent ?? '—',
    ai_suggested_category: item.suggested_category ?? '—',
    ai_urgency: 'MEDIUM',
    ai_sentiment: 'neutral',
    ai_extracted_entities: {},
    ai_confidence: item.original_confidence,
    ai_confidence_breakdown: emptyBreakdown(),
    ai_low_confidence_reasons: [],
    ai_multi_issue_detected: false,
  };
}

/**
 * Build a TriageCase from a full TriagePackage (the /triage/{id}
 * response). Vendor information is taken from `original_query.vendor_id`;
 * richer vendor fields stay null until we wire a /vendors/{id} fetch.
 */
function fromPackage(pkg: TriagePackageDto): TriageCase {
  const vendor: TriageVendor = {
    vendor_id: pkg.original_query?.vendor_id ?? '—',
  };
  const ar = pkg.analysis_result;
  return {
    query_id: pkg.query_id,
    received_at: pkg.original_query?.received_at ?? pkg.created_at,
    subject: pkg.original_query?.subject ?? '(no subject)',
    body: pkg.original_query?.body ?? '',
    vendor,
    status: 'IN_REVIEW',

    ai_intent: ar?.intent_classification ?? '—',
    ai_suggested_category: ar?.suggested_category ?? '—',
    ai_urgency: ar?.urgency_level ?? 'MEDIUM',
    ai_sentiment: ar?.sentiment ?? 'NEUTRAL',
    ai_extracted_entities: (ar?.extracted_entities as Readonly<Record<string, unknown>>) ?? {},
    ai_confidence: ar?.confidence_score ?? 0,
    ai_confidence_breakdown: normaliseBreakdown(pkg.confidence_breakdown),
    ai_low_confidence_reasons: [],
    ai_multi_issue_detected: ar?.multi_issue_detected ?? false,
  };
}

@Injectable({ providedIn: 'root' })
export class TriageStore {
  readonly #api = inject(TriageApiService);
  readonly #vendors = inject(VendorService);

  readonly #cases = signal<readonly TriageCase[]>([]);
  readonly #decisions = signal<readonly ReviewerDecision[]>([]);
  readonly #loading = signal<boolean>(false);
  readonly #loaded = signal<boolean>(false);
  readonly #error = signal<string | null>(null);

  readonly all = computed<readonly TriageCase[]>(() => this.#cases());
  readonly pending = computed<readonly TriageCase[]>(() =>
    this.#cases().filter((c) => c.status === 'PENDING_REVIEW'),
  );
  readonly inReview = computed<readonly TriageCase[]>(() =>
    this.#cases().filter((c) => c.status === 'IN_REVIEW'),
  );
  readonly completed = computed<readonly TriageCase[]>(() =>
    this.#cases().filter((c) => c.status === 'COMPLETED'),
  );
  readonly loading = this.#loading.asReadonly();
  readonly loaded = this.#loaded.asReadonly();
  readonly error = this.#error.asReadonly();

  byId(queryId: string): TriageCase | undefined {
    return this.#cases().find((c) => c.query_id === queryId);
  }

  /** Refresh the queue from /triage/queue (oldest first per backend). */
  async refresh(): Promise<void> {
    this.#loading.set(true);
    this.#error.set(null);
    try {
      const resp = await firstValueFrom(this.#api.listQueue(50));
      const mapped = (resp?.packages ?? []).map(fromQueueItem);
      this.#cases.set(mapped);
      this.#loaded.set(true);
    } catch (err: unknown) {
      this.#error.set(err instanceof Error ? err.message : 'Failed to load queue');
    } finally {
      this.#loading.set(false);
    }
  }

  /**
   * Fetch the rich Salesforce vendor profile for a triage case and
   * merge it into the case's vendor field. Called by the detail page
   * after loadPackage() returns and we know the vendor_id.
   *
   * Failures are swallowed (we keep what we already have) — vendor
   * profile is supplementary data, not critical to triage review.
   */
  async loadVendorProfile(queryId: string, vendorId: string): Promise<void> {
    if (!vendorId || vendorId === '—') return;
    try {
      const v: Vendor = await firstValueFrom(this.#vendors.getById(vendorId));
      const merged: TriageVendor = {
        vendor_id: v.vendor_id ?? vendorId,
        company_name: v.name ?? null,
        tier: mapTier(v.vendor_tier),
        // Backend doesn't currently expose account_manager / primary_contact
        // / annual_spend / industry on Vendor_Account__c — leave them null
        // and the UI will skip those rows gracefully.
        account_manager: null,
        primary_contact: null,
        annual_spend_usd: v.annual_revenue ?? null,
        industry: v.category ?? null,
      };
      this.#cases.update((list) =>
        list.map((c) =>
          c.query_id === queryId ? { ...c, vendor: { ...c.vendor, ...merged } } : c,
        ),
      );
    } catch {
      // Vendor lookup is best-effort — keep whatever's already on the case.
    }
  }

  /**
   * Hydrate one row in the store with full package detail. Called by
   * the detail page on mount so the case in the store has subject /
   * body / breakdown / extracted entities populated.
   */
  async loadPackage(queryId: string): Promise<TriageCase | undefined> {
    try {
      const pkg = await firstValueFrom(this.#api.getPackage(queryId));
      const detailed = fromPackage(pkg);
      this.#cases.update((list) => {
        const idx = list.findIndex((c) => c.query_id === queryId);
        if (idx === -1) return [...list, detailed];
        const next = [...list];
        next[idx] = { ...next[idx], ...detailed };
        return next;
      });
      return detailed;
    } catch (err: unknown) {
      this.#error.set(err instanceof Error ? err.message : `Failed to load ${queryId}`);
      return undefined;
    }
  }

  setStatus(queryId: string, status: TriageStatus): void {
    this.#cases.update((list) =>
      list.map((c) => (c.query_id === queryId ? { ...c, status } : c)),
    );
  }

  submitDecision(decision: ReviewerDecision): void {
    this.#decisions.update((list) => [...list, decision]);
    this.setStatus(decision.query_id, 'COMPLETED');
  }

  decisionFor(queryId: string): ReviewerDecision | undefined {
    return this.#decisions().find((d) => d.query_id === queryId);
  }
}
