import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  computed,
  inject,
  signal,
} from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { SyncBanner } from './mail/sync-banner';
import { FolderRail, type MailFilters } from './mail/folder-rail';
import { MailList, type MailSort } from './mail/mail-list';
import { MailDetail, type MailDetailAction } from './mail/mail-detail';
import { ComposeModal } from './mail/compose-modal';
import { MAIL_FOLDERS } from '../data/mail';
import type { MailFolderId, MailThread } from '../data/mail';
import { ENDPOINTS_MAIL } from '../data/endpoints';
import { RoleService } from '../services/role.service';
import { MailStore } from '../services/mail.store';
import { SessionService } from '../services/session.service';

const DEFAULT_FILTERS: MailFilters = {
  vendor: 'ALL',
  path: 'ALL',
  conf: 'ALL',
  date: 'ALL',
  sla: 'ALL',
  has_attach: false,
};

@Component({
  selector: 'vq-mail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    Icon,
    Mono,
    EndpointsButton,
    EndpointsDrawer,
    SyncBanner,
    FolderRail,
    MailList,
    MailDetail,
    ComposeModal,
  ],
  template: `
    <div class="flex flex-col fade-up" style="height: 100%;">
      <vq-mail-sync-banner />

      <div class="flex items-center justify-between px-6 py-3 border-b hairline bg-panel">
        <div>
          <div class="ink flex items-center gap-2" style="font-size:18px; font-weight:600; letter-spacing:-.02em;">
            Email management
            @if (mail.status() === 'live') {
              <span class="chip" style="color: var(--ok); border-color: var(--ok); font-size:10.5px;">
                <vq-icon name="check-circle" [size]="10" /> Live · {{ mail.threads().length }}
                message{{ mail.threads().length === 1 ? '' : 's' }}
              </span>
            } @else if (mail.status() === 'loading') {
              <span class="chip" style="font-size:10.5px;">
                <vq-icon name="rotate-cw" [size]="10" /> Loading…
              </span>
            } @else if (mail.status() === 'error') {
              <span
                class="chip"
                style="color: var(--bad); border-color: var(--bad); font-size:10.5px;"
                [title]="mail.error() ?? ''"
              >
                <vq-icon name="alert-circle" [size]="10" /> Live load failed: {{ mail.error() }}
              </span>
            } @else {
              <span
                class="chip"
                style="color: var(--muted); font-size:10.5px;"
                [title]="mockReason()"
              >
                <vq-icon name="info" [size]="10" /> Mock data — {{ mockReason() }}
              </span>
            }
          </div>
          <div class="muted mt-0.5" style="font-size:12px;">
            Unified vendor inbox · <vq-mono>{{ inboundCount() }}</vq-mono> messages · backed by
            <vq-mono>intake.email_messages</vq-mono> +
            <vq-mono>workflow.draft_responses</vq-mono>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button
            class="btn"
            (click)="refresh()"
            [disabled]="mail.status() === 'loading'"
            title="Reload from /emails"
          >
            <vq-icon name="rotate-cw" [size]="13" /> Refresh
          </button>
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
          <button class="btn btn-accent" (click)="composeOpen.set(true)">
            <vq-icon name="pen-line" [size]="13" /> Compose
            <vq-mono [size]="10" [color]="'rgba(255,255,255,.7)'" cssClass="ml-1">C</vq-mono>
          </button>
        </div>
      </div>

      <div class="flex-1 flex overflow-hidden">
        <vq-mail-folder-rail
          [folder]="folder()"
          [filters]="filters()"
          [counts]="counts()"
          (folderChange)="folder.set($event)"
          (filtersChange)="filters.set($event)"
          (composeRequested)="composeOpen.set(true)"
        />
        <vq-mail-list
          [rows]="filteredRows()"
          [selectedId]="selectedRow()?.message_id ?? null"
          [bulk]="bulk()"
          [search]="search()"
          [sort]="sort()"
          [folder]="folder()"
          (selectRow)="selectedId.set($event)"
          (toggleOne)="toggleOne($event)"
          (toggleAllRequested)="toggleAll()"
          (clearBulk)="bulk.set(empty())"
          (searchChange)="search.set($event)"
          (sortChange)="sort.set(asSort($event))"
        />
        <vq-mail-detail [row]="selectedRow()" (action)="onAction($event)" />
      </div>

      <vq-mail-compose-modal
        [open]="composeOpen()"
        (closed)="composeOpen.set(false)"
      />

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Email management · backend contract"
        subtitle="extends dashboard.py + admin.py · src/api/routes/*"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />
    </div>
  `,
})
export class MailPage {
  protected readonly role = inject(RoleService);
  protected readonly mail = inject(MailStore);
  readonly #session = inject(SessionService);

  /**
   * Self-diagnostic for the "Mock data" chip — tells the user why
   * they aren't seeing live data so they can fix it without opening
   * DevTools. Order of checks matches the conditions inside
   * MailStore.refresh().
   */
  protected mockReason(): string {
    if (!this.#session.authed()) return 'not signed in';
    if (this.#session.role() !== 'Admin')
      return `Admin role required (current: ${this.#session.role()})`;
    return 'auto-refresh has not run yet';
  }

  protected readonly folder = signal<MailFolderId>('inbox');
  protected readonly filters = signal<MailFilters>(DEFAULT_FILTERS);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly bulk = signal<ReadonlySet<string>>(new Set());
  protected readonly search = signal<string>('');
  protected readonly sort = signal<MailSort>('newest');
  protected readonly composeOpen = signal<boolean>(false);
  protected readonly endpointsOpen = signal<boolean>(false);

  protected readonly endpoints = ENDPOINTS_MAIL;
  protected readonly inboundCount = computed<number>(
    () => this.mail.threads().filter((r) => r._direction === 'inbound').length,
  );

  protected readonly flagged = signal<ReadonlySet<string>>(new Set());
  protected readonly archived = signal<ReadonlySet<string>>(new Set());

  // Avoid creating new MailThread objects when no manual flags are set.
  // Mapping every thread on every recompute cascades through filteredRows
  // -> selectedRow -> MailDetail -> InternalNotes, triggering O(n) work
  // and re-renders for what is usually a no-op. Only spend that cost when
  // the user has actually flagged a row.
  protected readonly allRows = computed<readonly MailThread[]>(() => {
    const flagSet = this.flagged();
    const base = this.mail.threads();
    if (flagSet.size === 0) return base;
    return base.map((r) =>
      flagSet.has(r.message_id) && !r._flagged ? { ...r, _flagged: true } : r,
    );
  });

  refresh(): void {
    void this.mail.refresh();
  }

  protected readonly folderRows = computed<readonly MailThread[]>(() => {
    const folder = this.folder();
    const archivedSet = this.archived();
    return this.allRows().filter((r) => {
      if (archivedSet.has(r.message_id) && folder !== 'archived') return false;
      switch (folder) {
        case 'all':
          return r._direction === 'inbound';
        case 'unread':
          return r._direction === 'inbound' && r._status === 'unread';
        case 'inbox':
          return r._direction === 'inbound' && r._status !== 'draft';
        case 'sent':
          return r._direction === 'outbound' && r._status === 'sent';
        case 'drafts':
          return r._status === 'draft';
        case 'awaiting':
          return r._direction === 'outbound' && r._sla_pct !== null;
        case 'ai_suggested':
          return r._direction === 'inbound' && r._has_ai_draft;
        case 'flagged':
          return r._flagged;
        case 'archived':
          return archivedSet.has(r.message_id);
        case 'spam':
          return false;
        default:
          return true;
      }
    });
  });

  protected readonly filteredRows = computed<readonly MailThread[]>(() => {
    const f = this.filters();
    const term = this.search().toLowerCase();
    let list = this.folderRows().filter((r) => {
      if (f.vendor !== 'ALL' && r.vendor_id !== f.vendor) return false;
      if (f.path !== 'ALL' && r.processing_path !== f.path) return false;
      if (f.conf === 'HIGH' && r.confidence_score < 0.85) return false;
      if (f.conf === 'MED' && (r.confidence_score < 0.6 || r.confidence_score >= 0.85))
        return false;
      if (f.conf === 'LOW' && r.confidence_score >= 0.6) return false;
      if (f.has_attach && r.attachments.length === 0) return false;
      if (f.sla !== 'ALL') {
        const p = r._sla_pct;
        if (p === null) return false;
        if (f.sla === 'OK' && p >= 70) return false;
        if (f.sla === 'RISK' && (p < 70 || p >= 95)) return false;
        if (f.sla === 'BAD' && p < 95) return false;
      }
      if (term) {
        const hit =
          r.subject.toLowerCase().includes(term) ||
          r.from_name.toLowerCase().includes(term) ||
          r.from_address.toLowerCase().includes(term) ||
          r.body_text.toLowerCase().includes(term) ||
          r.vendor_name.toLowerCase().includes(term) ||
          r.query_id.toLowerCase().includes(term);
        if (!hit) return false;
      }
      return true;
    });
    list = list.slice().sort((a, b) => {
      const sort = this.sort();
      if (sort === 'oldest')
        return new Date(a.received_at).getTime() - new Date(b.received_at).getTime();
      if (sort === 'confidence') return b.confidence_score - a.confidence_score;
      if (sort === 'priority') return (b._sla_pct ?? -1) - (a._sla_pct ?? -1);
      return new Date(b.received_at).getTime() - new Date(a.received_at).getTime();
    });
    return list;
  });

  protected readonly counts = computed<Readonly<Record<string, number>>>(() => {
    const archivedSet = this.archived();
    const out: Record<string, number> = {};
    for (const f of MAIL_FOLDERS) {
      let n = 0;
      for (const r of this.allRows()) {
        const a = archivedSet.has(r.message_id);
        if (a && f.id !== 'archived') continue;
        if (
          (f.id === 'all' && r._direction === 'inbound') ||
          (f.id === 'unread' && r._direction === 'inbound' && r._status === 'unread') ||
          (f.id === 'inbox' && r._direction === 'inbound' && r._status !== 'draft') ||
          (f.id === 'sent' && r._direction === 'outbound' && r._status === 'sent') ||
          (f.id === 'drafts' && r._status === 'draft') ||
          (f.id === 'awaiting' && r._direction === 'outbound' && r._sla_pct !== null) ||
          (f.id === 'ai_suggested' && r._direction === 'inbound' && r._has_ai_draft) ||
          (f.id === 'flagged' && r._flagged) ||
          (f.id === 'archived' && archivedSet.has(r.message_id))
        ) {
          n++;
        }
      }
      out[f.id] = n;
    }
    return out;
  });

  protected readonly selectedRow = computed<MailThread | null>(() => {
    const list = this.filteredRows();
    const id = this.selectedId();
    if (id === null) return list[0] ?? null;
    return list.find((r) => r.message_id === id) ?? list[0] ?? null;
  });

  protected toggleOne(id: string): void {
    const next = new Set(this.bulk());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.bulk.set(next);
  }

  protected toggleAll(): void {
    const sel = this.bulk();
    const list = this.filteredRows();
    if (sel.size > 0 && sel.size === list.length) {
      this.bulk.set(this.empty());
    } else {
      this.bulk.set(new Set(list.map((r) => r.message_id)));
    }
  }

  protected onAction(action: MailDetailAction): void {
    const r = this.selectedRow();
    if (!r) return;
    if (action === 'flag') {
      const next = new Set(this.flagged());
      if (next.has(r.message_id)) next.delete(r.message_id);
      else next.add(r.message_id);
      this.flagged.set(next);
    } else if (action === 'archive') {
      const next = new Set(this.archived());
      next.add(r.message_id);
      this.archived.set(next);
    }
  }

  protected empty(): ReadonlySet<string> {
    return new Set();
  }

  protected asSort(v: string): MailSort {
    if (v === 'oldest' || v === 'priority' || v === 'confidence') return v;
    return 'newest';
  }

  // J / K / C / E / F / `/`  shortcuts (skipped while typing in inputs).
  @HostListener('window:keydown', ['$event'])
  onKey(e: KeyboardEvent): void {
    const tag = (document.activeElement as HTMLElement | null)?.tagName?.toLowerCase() ?? '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    const list = this.filteredRows();
    const cur = this.selectedRow();
    if (e.key === 'j' || e.key === 'k') {
      e.preventDefault();
      if (list.length === 0) return;
      const idx = cur ? list.findIndex((r) => r.message_id === cur.message_id) : -1;
      const next = e.key === 'j' ? Math.min(list.length - 1, idx + 1) : Math.max(0, idx - 1);
      const target = list[next];
      if (target) this.selectedId.set(target.message_id);
    } else if (e.key === 'c') {
      e.preventDefault();
      this.composeOpen.set(true);
    } else if (e.key === '/') {
      e.preventDefault();
      const el = document.querySelector<HTMLInputElement>('input[placeholder="Search mail…"]');
      el?.focus();
    } else if (e.key === 'e' && cur) {
      e.preventDefault();
      const next = new Set(this.archived());
      next.add(cur.message_id);
      this.archived.set(next);
    } else if (e.key === 'f' && cur) {
      e.preventDefault();
      const next = new Set(this.flagged());
      if (next.has(cur.message_id)) next.delete(cur.message_id);
      else next.add(cur.message_id);
      this.flagged.set(next);
    }
  }
}
