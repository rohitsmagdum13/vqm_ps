export type PrefSection = 'profile' | 'notifications' | 'sla' | 'language';

export interface PrefNavItem {
  readonly id: PrefSection;
  readonly label: string;
  readonly ico: string;
}

export const PREF_NAV: readonly PrefNavItem[] = [
  { id: 'profile', label: 'Profile', ico: '👤' },
  { id: 'notifications', label: 'Notifications', ico: '🔔' },
  { id: 'sla', label: 'SLA Alerts', ico: '⏱️' },
  { id: 'language', label: 'Language', ico: '🌐' },
];

export interface PrefToggleRow {
  readonly id: string;
  readonly label: string;
  readonly desc: string;
  readonly defaultOn: boolean;
  readonly section: PrefSection;
}

export const PREF_TOGGLES: readonly PrefToggleRow[] = [
  {
    id: 'email-notif',
    label: 'Email notifications',
    desc: 'Updates on your queries via email',
    defaultOn: true,
    section: 'notifications',
  },
  {
    id: 'sla-breach',
    label: 'SLA breach alerts',
    desc: 'Alert 2 hours before SLA deadline',
    defaultOn: true,
    section: 'sla',
  },
  {
    id: 'ai-resolution',
    label: 'AI resolution notifications',
    desc: 'Notify when a draft resolution is ready',
    defaultOn: true,
    section: 'notifications',
  },
  {
    id: 'weekly-digest',
    label: 'Weekly digest',
    desc: 'Sunday summary of open queries',
    defaultOn: false,
    section: 'notifications',
  },
  {
    id: 'two-factor',
    label: 'Two-factor authentication',
    desc: 'Require OTP on every login',
    defaultOn: false,
    section: 'profile',
  },
];

export interface LanguageOption {
  readonly code: string;
  readonly label: string;
}

export const LANGUAGES: readonly LanguageOption[] = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी (Hindi)' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
];
