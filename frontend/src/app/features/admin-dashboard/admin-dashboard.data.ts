export type Period = 'daily' | 'weekly' | 'monthly';

export type KpiTone = 'tg' | 'tr' | 'ta';
export type PriorityAccent = 'error' | 'warn' | 'primary' | 'accent';

export interface AdminKpi {
  readonly lbl: string;
  readonly v: string;
  readonly d: string;
  readonly tone: KpiTone;
  readonly accent: 'primary' | 'success' | 'warn' | 'error';
  readonly ico: string;
}

export interface AdminBreakdownRow {
  readonly lbl: string;
  readonly n: number;
  readonly pct: number;
  readonly accent: PriorityAccent;
}

export interface AdminAlert {
  readonly ico: string;
  readonly ttl: string;
  readonly sub: string;
  readonly severity: 'error' | 'warn' | 'info';
}

export interface AdminPeriodData {
  readonly sub: string;
  readonly chartSub: string;
  readonly labels: readonly string[];
  readonly resolved: readonly number[];
  readonly pending: readonly number[];
  readonly breached: readonly number[];
  readonly kpis: readonly AdminKpi[];
  readonly breakdown: readonly AdminBreakdownRow[];
  readonly alerts: readonly AdminAlert[];
}

export type AdminData = Readonly<Record<Period, AdminPeriodData>>;

export const AD_DATA: AdminData = {
  daily: {
    sub: 'Real-time VQMS performance · Last 24 hours',
    chartSub: 'Hourly resolved / pending / breached · last 12 hours',
    labels: ['00', '02', '04', '06', '08', '10', '12', '14', '16', '18', '20', '22'],
    resolved: [3, 2, 4, 6, 9, 12, 14, 11, 13, 15, 10, 7],
    pending: [1, 1, 2, 3, 4, 5, 6, 4, 4, 3, 2, 1],
    breached: [0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0],
    kpis: [
      { lbl: 'Queries today', v: '47', d: '↑12%', tone: 'tg', accent: 'primary', ico: '📬' },
      { lbl: 'Resolved', v: '38', d: '81% rate', tone: 'tg', accent: 'success', ico: '✅' },
      { lbl: 'Avg response', v: '2.1h', d: '↓18%', tone: 'tg', accent: 'warn', ico: '⏱️' },
      { lbl: 'SLA breaches', v: '2', d: '1 critical', tone: 'tr', accent: 'error', ico: '⚠️' },
    ],
    breakdown: [
      { lbl: 'Critical', n: 3, pct: 6, accent: 'error' },
      { lbl: 'High', n: 11, pct: 23, accent: 'warn' },
      { lbl: 'Medium', n: 24, pct: 51, accent: 'primary' },
      { lbl: 'Low', n: 9, pct: 20, accent: 'accent' },
    ],
    alerts: [
      { ico: '🔴', ttl: 'VQ-2025-0039 SLA breached', sub: 'Invoice dispute · 4h overdue · ACME Finance', severity: 'error' },
      { ico: '⚠️', ttl: 'Bedrock at 78% of monthly budget', sub: '$2,340 / $3,000 · forecast $2,905', severity: 'warn' },
      { ico: '🟡', ttl: '2 queries nearing SLA', sub: 'VQ-2025-0041 (5h) · VQ-2025-0045 (3h)', severity: 'info' },
    ],
  },
  weekly: {
    sub: 'Weekly operations review · Mar 24 – Mar 30',
    chartSub: 'Daily volume · last 7 days',
    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    resolved: [38, 42, 45, 51, 48, 22, 18],
    pending: [8, 10, 9, 12, 11, 5, 4],
    breached: [2, 1, 3, 2, 1, 0, 1],
    kpis: [
      { lbl: 'Queries this week', v: '284', d: '↑8% vs last', tone: 'tg', accent: 'primary', ico: '📬' },
      { lbl: 'Resolved', v: '231', d: '81% rate', tone: 'tg', accent: 'success', ico: '✅' },
      { lbl: 'Avg response', v: '2.4h', d: 'SLA target 4h', tone: 'tg', accent: 'warn', ico: '⏱️' },
      { lbl: 'SLA breaches', v: '10', d: '3.5% of total', tone: 'ta', accent: 'error', ico: '⚠️' },
    ],
    breakdown: [
      { lbl: 'Critical', n: 14, pct: 5, accent: 'error' },
      { lbl: 'High', n: 68, pct: 24, accent: 'warn' },
      { lbl: 'Medium', n: 142, pct: 50, accent: 'primary' },
      { lbl: 'Low', n: 60, pct: 21, accent: 'accent' },
    ],
    alerts: [
      { ico: '🔴', ttl: 'Contracts category trending up', sub: '+31% volume vs last week · review capacity', severity: 'error' },
      { ico: '⚠️', ttl: 'Ravi Krishnan · 3 escalations this week', sub: 'ACME Finance account needs review', severity: 'warn' },
      { ico: '🟡', ttl: 'Avg response creeping up Tue–Thu', sub: 'Peak 3.1h · consider capacity scaling', severity: 'info' },
    ],
  },
  monthly: {
    sub: 'Monthly executive summary · March 2026',
    chartSub: 'Weekly resolved / pending / breached · last 4 weeks',
    labels: ['W1', 'W2', 'W3', 'W4'],
    resolved: [210, 245, 263, 284],
    pending: [38, 42, 48, 52],
    breached: [8, 6, 9, 10],
    kpis: [
      { lbl: 'Queries this month', v: '1,247', d: '↑14% MoM', tone: 'tg', accent: 'primary', ico: '📬' },
      { lbl: 'Resolved', v: '1,002', d: '80.4% rate', tone: 'tg', accent: 'success', ico: '✅' },
      { lbl: 'Avg response', v: '2.6h', d: '↓12% MoM', tone: 'tg', accent: 'warn', ico: '⏱️' },
      { lbl: 'SLA breaches', v: '33', d: '2.6% of total', tone: 'ta', accent: 'error', ico: '⚠️' },
    ],
    breakdown: [
      { lbl: 'Critical', n: 58, pct: 5, accent: 'error' },
      { lbl: 'High', n: 299, pct: 24, accent: 'warn' },
      { lbl: 'Medium', n: 623, pct: 50, accent: 'primary' },
      { lbl: 'Low', n: 267, pct: 21, accent: 'accent' },
    ],
    alerts: [
      { ico: '📈', ttl: 'Record month for AI resolutions', sub: '72% resolved by AI (vs 58% in Feb)', severity: 'info' },
      { ico: '⚠️', ttl: 'Bedrock spend forecast +18% in April', sub: 'Review caching strategy with platform team', severity: 'warn' },
      { ico: '🟡', ttl: 'Tech Support backlog growing', sub: '+42% vs Feb · 12 queries over 48h', severity: 'info' },
    ],
  },
};

