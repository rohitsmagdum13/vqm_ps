import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EmailService } from './email.service';
import { EmailsStore } from './emails.store';
import type {
  MailAttachmentDownload,
  MailChain,
  MailChainList,
  MailStats,
} from '../shared/models/email';

function makeChain(overrides: Partial<MailChain> = {}): MailChain {
  return {
    conversation_id: 'conv-1',
    status: 'New',
    priority: 'Medium',
    mail_items: [
      {
        query_id: 'VQ-2026-0001',
        sender: { name: 'Alice Vendor', email: 'alice@vendor.com' },
        subject: 'Invoice follow-up',
        body: 'Hi, checking on invoice status.',
        timestamp: '2026-04-19T10:00:00+05:30',
        attachments: [],
        thread_status: 'NEW',
      },
    ],
    ...overrides,
  };
}

function makeStats(overrides: Partial<MailStats> = {}): MailStats {
  return {
    total_emails: 10,
    new_count: 4,
    reopened_count: 1,
    resolved_count: 5,
    priority_breakdown: { High: 2, Medium: 5, Low: 3 },
    today_count: 3,
    this_week_count: 8,
    ...overrides,
  };
}

function makeList(chains: readonly MailChain[] = [makeChain()]): MailChainList {
  return {
    total: chains.length,
    page: 1,
    page_size: 20,
    mail_chains: chains,
  };
}

describe('EmailsStore', () => {
  let store: EmailsStore;
  let listChains: ReturnType<typeof vi.fn>;
  let getStats: ReturnType<typeof vi.fn>;
  let getChain: ReturnType<typeof vi.fn>;
  let getAttachmentDownload: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    listChains = vi.fn(() => of(makeList()));
    getStats = vi.fn(() => of(makeStats()));
    getChain = vi.fn((queryId: string) => of(makeChain({
      mail_items: [
        {
          query_id: queryId,
          sender: { name: 'Alice Vendor', email: 'alice@vendor.com' },
          subject: 'Invoice follow-up',
          body: 'Full body.',
          timestamp: '2026-04-19T10:00:00+05:30',
          attachments: [],
          thread_status: 'NEW',
        },
      ],
    })));
    getAttachmentDownload = vi.fn(() =>
      of<MailAttachmentDownload>({
        attachment_id: 'att-1',
        filename: 'invoice.pdf',
        download_url: 'https://example.com/signed',
        expires_in_seconds: 3600,
      }),
    );

    TestBed.configureTestingModule({
      providers: [
        {
          provide: EmailService,
          useValue: { listChains, getStats, getChain, getAttachmentDownload },
        },
      ],
    });
    store = TestBed.inject(EmailsStore);
  });

  it('starts empty with sensible defaults', () => {
    expect(store.chains().length).toBe(0);
    expect(store.stats()).toBe(null);
    expect(store.loading()).toBe(false);
    expect(store.hasLoaded()).toBe(false);
    expect(store.status()).toBe(null);
    expect(store.priority()).toBe(null);
    expect(store.page()).toBe(1);
  });

  it('refresh loads chains and stats in parallel', () => {
    store.refresh();
    expect(listChains).toHaveBeenCalledTimes(1);
    expect(getStats).toHaveBeenCalledTimes(1);
    expect(store.chains().length).toBe(1);
    expect(store.stats()?.total_emails).toBe(10);
    expect(store.loading()).toBe(false);
    expect(store.hasLoaded()).toBe(true);
  });

  it('filterCounts mirrors stats', () => {
    store.refresh();
    const c = store.filterCounts();
    expect(c.all).toBe(10);
    expect(c.new).toBe(4);
    expect(c.reopened).toBe(1);
    expect(c.resolved).toBe(5);
  });

  it('setStatus resets page to 1 and refetches', () => {
    store.refresh();
    listChains.mockClear();
    store.setStatus('New');
    expect(store.status()).toBe('New');
    expect(store.page()).toBe(1);
    expect(listChains).toHaveBeenCalledTimes(1);
    const query = listChains.mock.calls[0][0];
    expect(query.status).toBe('New');
  });

  it('setStatus is a no-op when unchanged', () => {
    store.refresh();
    listChains.mockClear();
    store.setStatus(null);
    expect(listChains).not.toHaveBeenCalled();
  });

  it('setSearch debounce-friendly update triggers refresh with trimmed term', () => {
    store.refresh();
    listChains.mockClear();
    store.setSearch('invoice');
    expect(listChains).toHaveBeenCalledTimes(1);
    expect(listChains.mock.calls[0][0].search).toBe('invoice');
  });

  it('setPage clamps below 1', () => {
    store.refresh();
    listChains.mockClear();
    store.setPage(0);
    expect(store.page()).toBe(1);
  });

  it('setSort fires refresh with new field and order', () => {
    store.refresh();
    listChains.mockClear();
    store.setSort('priority', 'asc');
    expect(listChains).toHaveBeenCalledTimes(1);
    expect(listChains.mock.calls[0][0]).toMatchObject({
      sort_by: 'priority',
      sort_order: 'asc',
    });
  });

  it('selectChain fetches detail and stores it', () => {
    store.refresh();
    store.selectChain('VQ-2026-0001');
    expect(getChain).toHaveBeenCalledWith('VQ-2026-0001');
    expect(store.selectedQueryId()).toBe('VQ-2026-0001');
    expect(store.selectedChain()?.mail_items[0].query_id).toBe('VQ-2026-0001');
  });

  it('selectChain(null) clears detail', () => {
    store.refresh();
    store.selectChain('VQ-2026-0001');
    store.selectChain(null);
    expect(store.selectedQueryId()).toBe(null);
    expect(store.selectedChain()).toBe(null);
  });

  it('downloadAttachment resolves with presigned URL', async () => {
    const originalOpen = globalThis.window?.open;
    if (globalThis.window) {
      globalThis.window.open = vi.fn() as unknown as typeof window.open;
    }
    const url = await store.downloadAttachment('VQ-2026-0001', 'att-1');
    expect(url).toBe('https://example.com/signed');
    expect(getAttachmentDownload).toHaveBeenCalledWith('VQ-2026-0001', 'att-1');
    if (globalThis.window && originalOpen) {
      globalThis.window.open = originalOpen;
    }
  });

  it('refresh surfaces HttpErrorResponse detail as error signal', () => {
    listChains.mockReturnValueOnce(throwError(() => ({
      status: 503,
      error: { detail: 'Database unavailable' },
    })));
    store.refresh();
    expect(store.error()).toBe('Database unavailable');
    expect(store.loading()).toBe(false);
    expect(store.hasLoaded()).toBe(true);
  });
});
