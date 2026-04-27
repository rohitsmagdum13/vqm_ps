import type { Priority } from '../../shared/models/query';

export interface WizardDraft {
  readonly type: string;
  readonly subject: string;
  readonly desc: string;
  readonly priority: Priority;
  readonly ref: string;
  readonly files: readonly File[];
}

export const EMPTY_DRAFT: WizardDraft = {
  type: '',
  subject: '',
  desc: '',
  priority: 'Medium',
  ref: '',
  files: [],
};

/** Per-file limit enforced server-side; we mirror it in the UI so the
 *  vendor sees a clear "too big" message before they hit submit. */
export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
/** Total upload cap across all files for a single submission. */
export const MAX_TOTAL_ATTACHMENT_BYTES = 50 * 1024 * 1024;
/** Max number of files the backend will accept per query. */
export const MAX_ATTACHMENT_COUNT = 10;
/** Extensions the backend rejects outright — block them client-side too. */
export const BLOCKED_ATTACHMENT_EXTENSIONS: readonly string[] = [
  '.exe',
  '.bat',
  '.cmd',
  '.ps1',
  '.sh',
  '.js',
];

export type WizardStep = 1 | 2 | 3 | 4 | 5;

export const SLA_BY_PRIORITY: Readonly<Record<Priority, string>> = {
  Critical: '2 hours',
  High: '4 hours',
  Medium: '8 hours',
  Low: '24 hours',
};
