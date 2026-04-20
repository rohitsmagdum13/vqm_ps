import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { QueriesStore } from './queries.store';
import type { Query } from '../shared/models/query';

function makeQuery(overrides: Partial<Query> = {}): Query {
  return {
    id: 'VQ-TEST-0001',
    subj: 'Test subject',
    type: 'Contract Query',
    pri: 'Medium',
    status: 'Open',
    submitted: 'Today',
    sla: '4h remaining',
    slaCls: 'sla-ok',
    agent: 'ResolutionAgent',
    tl: [],
    ai: '',
    msgs: [],
    ...overrides,
  };
}

describe('QueriesStore', () => {
  let store: QueriesStore;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    store = TestBed.inject(QueriesStore);
  });

  it('seeds a non-empty queries list', () => {
    expect(store.queries().length).toBeGreaterThan(0);
  });

  it('computes stats that do not exceed total', () => {
    const { open, inProgress, awaiting, resolved, total } = store.stats();
    expect(open + inProgress + awaiting + resolved).toBeLessThanOrEqual(total);
  });

  it('activeCount equals open + inProgress + awaiting', () => {
    const s = store.stats();
    expect(store.activeCount()).toBe(s.open + s.inProgress + s.awaiting);
  });

  it('filters by status', () => {
    store.setStatusFilter('Resolved');
    expect(store.filtered().every((q) => q.status === 'Resolved')).toBe(true);
  });

  it('combines status and priority filters (AND)', () => {
    store.setStatusFilter('Open');
    store.setPriorityFilter('High');
    expect(store.filtered().every((q) => q.status === 'Open' && q.pri === 'High')).toBe(true);
  });

  it('clearFilters resets both filters and expands results to full set', () => {
    store.setStatusFilter('Resolved');
    store.setPriorityFilter('High');
    store.clearFilters();
    expect(store.statusFilter()).toBe('');
    expect(store.priorityFilter()).toBe('');
    expect(store.filtered().length).toBe(store.queries().length);
  });

  it('returns at most 4 recent queries', () => {
    expect(store.recent().length).toBeLessThanOrEqual(4);
  });

  it('add prepends immutably', () => {
    const before = store.queries();
    store.add(makeQuery({ id: 'VQ-NEW-9999' }));
    const after = store.queries();
    expect(after.length).toBe(before.length + 1);
    expect(after[0].id).toBe('VQ-NEW-9999');
    expect(after).not.toBe(before);
  });

  it('findById returns a match or undefined', () => {
    const first = store.queries()[0];
    expect(store.findById(first.id)?.id).toBe(first.id);
    expect(store.findById('not-a-real-id')).toBeUndefined();
  });

  it('appendMessage adds to target without touching siblings', () => {
    const target = store.queries()[0];
    const sibling = store.queries()[1];
    store.appendMessage(target.id, { f: 'vendor', t: 'hello', ts: 'Just now' });
    expect(store.findById(target.id)?.msgs.length).toBe(target.msgs.length + 1);
    expect(store.queries()[1]).toBe(sibling);
  });
});
