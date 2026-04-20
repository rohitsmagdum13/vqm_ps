import type { Priority } from '../../shared/models/query';

export interface WizardDraft {
  readonly type: string;
  readonly subject: string;
  readonly desc: string;
  readonly priority: Priority;
  readonly ref: string;
}

export const EMPTY_DRAFT: WizardDraft = {
  type: '',
  subject: '',
  desc: '',
  priority: 'Medium',
  ref: '',
};

export type WizardStep = 1 | 2 | 3 | 4 | 5;

export const SLA_BY_PRIORITY: Readonly<Record<Priority, string>> = {
  Critical: '2 hours',
  High: '4 hours',
  Medium: '8 hours',
  Low: '24 hours',
};
