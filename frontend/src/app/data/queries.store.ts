import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { AuthService } from '../core/auth/auth.service';
import type { Priority, Query, QueryMessage, QueryStatus } from '../shared/models/query';
import {
  QueryService,
  type QueryDetail,
  type QueryListItem,
} from './query.service';

export interface QueryStats {
  readonly total: number;
  readonly open: number;
  readonly inProgress: number;
  readonly awaiting: number;
  readonly resolved: number;
  readonly breached: number;
}

function errorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const detail =
      err.error && typeof err.error === 'object' && 'detail' in err.error
        ? (err.error as { detail?: unknown }).detail
        : null;
    if (typeof detail === 'string' && detail.length > 0) return detail;
    if (err.status === 0) return 'Cannot reach the server. Is the backend running?';
    if (err.status === 401) return 'Session expired. Please sign in again.';
    if (err.status === 403) return 'Not authorized.';
    return `Request failed (${err.status})`;
  }
  if (err instanceof Error) return err.message;
  return 'Unexpected error';
}

const QUERY_TYPE_LABEL: Record<string, string> = {
  RETURN_REFUND: 'Return & Refund',
  GENERAL_INQUIRY: 'General Inquiry',
  CATALOG_PRICING: 'Catalog & Pricing',
  CONTRACT_QUERY: 'Contract Query',
  PURCHASE_ORDER: 'Purchase Order',
  SLA_BREACH_REPORT: 'SLA Breach Report',
  DELIVERY_SHIPMENT: 'Delivery & Shipment',
  INVOICE_PAYMENT: 'Invoice & Payment',
  COMPLIANCE_AUDIT: 'Compliance & Audit',
  TECHNICAL_SUPPORT: 'Technical Support',
  ONBOARDING: 'Onboarding',
  QUALITY_ISSUE: 'Quality Issue',
};

const STATUS_MAP: Record<string, QueryStatus> = {
  RECEIVED: 'Open',
  QUEUED: 'Open',
  ANALYZING: 'In Progress',
  ROUTING: 'In Progress',
  KB_SEARCHING: 'In Progress',
  DRAFTING: 'In Progress',
  QUALITY_CHECK: 'In Progress',
  AWAITING_VENDOR: 'Awaiting Vendor',
  AWAITING_TEAM: 'In Progress',
  HUMAN_REVIEW: 'In Progress',
  RESOLVED: 'Resolved',
  CLOSED: 'Resolved',
  REOPENED: 'In Progress',
  SLA_BREACHED: 'Breached',
};

function mapStatus(raw: string): QueryStatus {
  return STATUS_MAP[raw?.toUpperCase()] ?? 'Open';
}

function mapPriority(raw: string | null | undefined): Priority {
  const v = (raw ?? 'MEDIUM').toUpperCase();
  if (v === 'CRITICAL') return 'Critical';
  if (v === 'HIGH') return 'High';
  if (v === 'LOW') return 'Low';
  return 'Medium';
}

const RELATIVE_FMT = new Intl.DateTimeFormat('en-IN', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

function formatSubmitted(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return RELATIVE_FMT.format(d);
}

function formatSla(deadlineIso: string | null, status: string): {
  readonly sla: string;
  readonly slaCls: 'sla-ok' | 'sla-brch';
} {
  if (status?.toUpperCase() === 'SLA_BREACHED') {
    return { sla: 'Breached', slaCls: 'sla-brch' };
  }
  if (!deadlineIso) {
    return { sla: '—', slaCls: 'sla-ok' };
  }
  const d = new Date(deadlineIso);
  if (Number.isNaN(d.getTime())) return { sla: deadlineIso, slaCls: 'sla-ok' };
  const diffMs = d.getTime() - Date.now();
  if (diffMs <= 0) return { sla: 'Breached', slaCls: 'sla-brch' };
  const hours = Math.floor(diffMs / 3600000);
  const minutes = Math.floor((diffMs % 3600000) / 60000);
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return { sla: `${days}d ${hours % 24}h`, slaCls: 'sla-ok' };
  }
  return { sla: `${hours}h ${minutes}m`, slaCls: 'sla-ok' };
}

function listItemToQuery(row: QueryListItem): Query {
  const { sla, slaCls } = formatSla(row.sla_deadline, row.status);
  const typeLabel = row.query_type
    ? QUERY_TYPE_LABEL[row.query_type] ?? row.query_type
    : '—';
  return {
    id: row.query_id,
    subj: row.subject ?? '(no subject)',
    type: typeLabel,
    pri: mapPriority(row.priority),
    status: mapStatus(row.status),
    submitted: formatSubmitted(row.created_at),
    sla,
    slaCls,
    agent: row.source === 'email' ? 'Email' : 'Portal',
    tl: [],
    ai: '',
    msgs: [],
  };
}

function detailToQuery(d: QueryDetail): Query {
  const base = listItemToQuery(d);
  const msgs: QueryMessage[] = [];
  if (d.description) {
    msgs.push({ f: 'vendor', t: d.description, ts: formatSubmitted(d.created_at) });
  }
  return {
    ...base,
    tl: [
      { c: '#10B981', t: 'Query received & logged by VQMS', ts: formatSubmitted(d.created_at) },
      { c: '#3c2cda', t: `Status: ${d.status}`, ts: formatSubmitted(d.updated_at) },
    ],
    ai: '',
    msgs,
  };
}

@Injectable({ providedIn: 'root' })
export class QueriesStore {
  readonly #svc = inject(QueryService);
  readonly #auth = inject(AuthService);

  readonly #queries = signal<readonly Query[]>([]);
  readonly #statusFilter = signal<QueryStatus | ''>('');
  readonly #priorityFilter = signal<Priority | ''>('');
  readonly #loading = signal<boolean>(false);
  readonly #error = signal<string | null>(null);
  readonly #hasLoaded = signal<boolean>(false);
  readonly #selected = signal<Query | null>(null);

  readonly queries = this.#queries.asReadonly();
  readonly statusFilter = this.#statusFilter.asReadonly();
  readonly priorityFilter = this.#priorityFilter.asReadonly();
  readonly loading = this.#loading.asReadonly();
  readonly error = this.#error.asReadonly();
  readonly hasLoaded = this.#hasLoaded.asReadonly();
  readonly selected = this.#selected.asReadonly();

  readonly filtered = computed<readonly Query[]>(() => {
    const s = this.#statusFilter();
    const p = this.#priorityFilter();
    return this.#queries().filter(
      (q) => (s === '' || q.status === s) && (p === '' || q.pri === p),
    );
  });

  readonly recent = computed<readonly Query[]>(() => this.#queries().slice(0, 4));

  readonly stats = computed<QueryStats>(() => {
    const all = this.#queries();
    return {
      total: all.length,
      open: all.filter((q) => q.status === 'Open').length,
      inProgress: all.filter((q) => q.status === 'In Progress').length,
      awaiting: all.filter((q) => q.status === 'Awaiting Vendor').length,
      resolved: all.filter((q) => q.status === 'Resolved').length,
      breached: all.filter((q) => q.slaCls === 'sla-brch').length,
    };
  });

  readonly activeCount = computed<number>(() => {
    const s = this.stats();
    return s.open + s.inProgress + s.awaiting;
  });

  refresh(): void {
    const vendorId = this.#auth.vendorId();
    if (!vendorId) {
      this.#error.set('No vendor ID on this session.');
      this.#hasLoaded.set(true);
      return;
    }
    this.#loading.set(true);
    this.#error.set(null);
    this.#svc.list(vendorId).subscribe({
      next: (resp) => {
        this.#queries.set(resp.queries.map(listItemToQuery));
        this.#loading.set(false);
        this.#hasLoaded.set(true);
      },
      error: (err: unknown) => {
        this.#error.set(errorMessage(err));
        this.#loading.set(false);
        this.#hasLoaded.set(true);
      },
    });
  }

  loadDetail(queryId: string): void {
    const vendorId = this.#auth.vendorId();
    if (!vendorId || !queryId) {
      this.#selected.set(null);
      return;
    }
    const cached = this.#queries().find((q) => q.id === queryId);
    if (cached) this.#selected.set(cached);
    this.#svc.get(vendorId, queryId).subscribe({
      next: (d) => this.#selected.set(detailToQuery(d)),
      error: (err: unknown) => {
        this.#error.set(errorMessage(err));
        if (!cached) this.#selected.set(null);
      },
    });
  }

  findById(id: string): Query | undefined {
    return this.#queries().find((q) => q.id === id);
  }

  setStatusFilter(v: QueryStatus | ''): void {
    this.#statusFilter.set(v);
  }

  setPriorityFilter(v: Priority | ''): void {
    this.#priorityFilter.set(v);
  }

  clearFilters(): void {
    this.#statusFilter.set('');
    this.#priorityFilter.set('');
  }

  addFromServer(row: QueryListItem): void {
    const q = listItemToQuery(row);
    this.#queries.update((xs) => [q, ...xs.filter((x) => x.id !== q.id)]);
  }

  appendMessage(_id: string, _msg: QueryMessage): void {
    // Reply-to-query is not wired to a backend endpoint yet — kept for UI compat.
  }
}
