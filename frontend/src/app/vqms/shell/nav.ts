import type { Query } from '../data/models';
import { MAIL_THREADS } from '../data/mail';

export interface NavItem {
  readonly id: string;
  readonly label: string;
  readonly icon: string;
  readonly route: string;
  readonly badge?: (queries: readonly Query[]) => number;
}

export const NAV: readonly NavItem[] = [
  { id: 'overview', label: 'Overview', icon: 'layout-dashboard', route: '/app/overview' },
  {
    id: 'inbox',
    label: 'Query inbox',
    icon: 'inbox',
    route: '/app/inbox',
    badge: (q) =>
      q.filter((it) => !['RESOLVED', 'CLOSED', 'MERGED_INTO_PARENT'].includes(it.status)).length,
  },
  {
    id: 'mail',
    label: 'Email management',
    icon: 'mail-search',
    route: '/app/mail',
    badge: () =>
      MAIL_THREADS.filter((r) => r._direction === 'inbound' && r._status === 'unread').length,
  },
  {
    id: 'triage',
    label: 'Triage queue',
    icon: 'user-check',
    route: '/app/triage',
    badge: (q) =>
      q.filter((it) => it.processing_path === 'C' && it.status === 'PAUSED').length,
  },
  { id: 'vendors', label: 'Vendors', icon: 'building-2', route: '/app/vendors' },
  { id: 'email', label: 'Email pipeline', icon: 'mail', route: '/app/email' },
  { id: 'kb', label: 'Knowledge base', icon: 'book-open', route: '/app/kb' },
  { id: 'bulk', label: 'Bulk actions', icon: 'list-checks', route: '/app/bulk' },
  { id: 'audit', label: 'Audit log', icon: 'scroll-text', route: '/app/audit' },
  { id: 'admin', label: 'Admin', icon: 'shield', route: '/app/admin' },
];
