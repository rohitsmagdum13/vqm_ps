import type {
  AuditEntry,
  ConfidenceBand,
  Contact,
  Contract,
  FeatureFlag,
  HourlyRow,
  IntentBucket,
  Integration,
  KbArticle,
  PipelineStage,
  Query,
  Queue,
  SourceUsed,
  TeamSla,
  ThreadMessage,
  UserRow,
  Vendor,
  VolumeRow,
} from './models';

export const VENDORS: readonly Vendor[] = [
  {
    vendor_id: 'V-001',
    name: 'Cloudwave Hosting',
    website: 'cloudwave.io',
    tier: 'PLATINUM',
    category: 'Cloud Infrastructure',
    payment_terms: 'NET 45',
    annual_revenue: 84_200_000,
    sla_response_hours: 2,
    sla_resolution_days: 1,
    status: 'ACTIVE',
    city: 'Seattle',
    state: 'WA',
    country: 'USA',
    onboarded_date: '2019-03-12',
    health: 98,
    open_queries: 4,
    p1_open: 0,
  },
  {
    vendor_id: 'V-002',
    name: 'Northwind Logistics',
    website: 'northwindlog.com',
    tier: 'GOLD',
    category: 'Logistics',
    payment_terms: 'NET 60',
    annual_revenue: 41_800_000,
    sla_response_hours: 4,
    sla_resolution_days: 3,
    status: 'ACTIVE',
    city: 'Chicago',
    state: 'IL',
    country: 'USA',
    onboarded_date: '2020-08-04',
    health: 86,
    open_queries: 7,
    p1_open: 1,
  },
  {
    vendor_id: 'V-003',
    name: 'Sigma Data Labs',
    website: 'sigmadata.ai',
    tier: 'PLATINUM',
    category: 'Data & Analytics',
    payment_terms: 'NET 30',
    annual_revenue: 62_000_000,
    sla_response_hours: 2,
    sla_resolution_days: 1,
    status: 'ACTIVE',
    city: 'Austin',
    state: 'TX',
    country: 'USA',
    onboarded_date: '2021-01-22',
    health: 92,
    open_queries: 3,
    p1_open: 0,
  },
  {
    vendor_id: 'V-004',
    name: 'Helios Print Co.',
    website: 'helios.print',
    tier: 'SILVER',
    category: 'Office Services',
    payment_terms: 'NET 30',
    annual_revenue: 8_400_000,
    sla_response_hours: 8,
    sla_resolution_days: 5,
    status: 'ACTIVE',
    city: 'Toronto',
    state: 'ON',
    country: 'CAN',
    onboarded_date: '2022-06-15',
    health: 71,
    open_queries: 12,
    p1_open: 0,
  },
  {
    vendor_id: 'V-005',
    name: 'Bramble & Hart LLP',
    website: 'bramblehart.com',
    tier: 'GOLD',
    category: 'Legal Services',
    payment_terms: 'NET 30',
    annual_revenue: 19_900_000,
    sla_response_hours: 4,
    sla_resolution_days: 3,
    status: 'ACTIVE',
    city: 'London',
    state: '—',
    country: 'GBR',
    onboarded_date: '2018-11-30',
    health: 88,
    open_queries: 2,
    p1_open: 0,
  },
  {
    vendor_id: 'V-006',
    name: 'Yamasaki Hardware',
    website: 'yamasaki.co.jp',
    tier: 'BRONZE',
    category: 'Hardware Supply',
    payment_terms: 'NET 60',
    annual_revenue: 3_200_000,
    sla_response_hours: 12,
    sla_resolution_days: 7,
    status: 'ACTIVE',
    city: 'Osaka',
    state: '—',
    country: 'JPN',
    onboarded_date: '2023-04-10',
    health: 64,
    open_queries: 9,
    p1_open: 2,
  },
  {
    vendor_id: 'V-007',
    name: 'Continental Steelworks',
    website: 'continental-steel.de',
    tier: 'PLATINUM',
    category: 'Manufacturing',
    payment_terms: 'NET 45',
    annual_revenue: 128_500_000,
    sla_response_hours: 2,
    sla_resolution_days: 1,
    status: 'ACTIVE',
    city: 'Hamburg',
    state: '—',
    country: 'DEU',
    onboarded_date: '2017-02-08',
    health: 95,
    open_queries: 1,
    p1_open: 0,
  },
  {
    vendor_id: 'V-008',
    name: 'Greenline Catering',
    website: 'greenline.com',
    tier: 'SILVER',
    category: 'Office Services',
    payment_terms: 'NET 30',
    annual_revenue: 6_100_000,
    sla_response_hours: 8,
    sla_resolution_days: 5,
    status: 'ACTIVE',
    city: 'Brooklyn',
    state: 'NY',
    country: 'USA',
    onboarded_date: '2022-09-01',
    health: 78,
    open_queries: 5,
    p1_open: 0,
  },
];

export const CONTACTS: Readonly<Record<string, readonly Contact[]>> = {
  'V-001': [
    {
      name: 'Marcus Holloway',
      role: 'Account Manager',
      email: 'm.holloway@cloudwave.io',
      phone: '+1 206 555 0188',
    },
    {
      name: 'Priya Raman',
      role: 'Billing Lead',
      email: 'billing@cloudwave.io',
      phone: '+1 206 555 0190',
    },
    {
      name: 'Dao Nguyen',
      role: 'Technical Liaison',
      email: 'dao.n@cloudwave.io',
      phone: '+1 206 555 0142',
    },
  ],
  'V-002': [
    {
      name: 'Greta Lindqvist',
      role: 'Account Manager',
      email: 'g.lindqvist@northwindlog.com',
      phone: '+1 312 555 0227',
    },
    {
      name: 'Owen Adesina',
      role: 'Operations',
      email: 'ops@northwindlog.com',
      phone: '+1 312 555 0231',
    },
  ],
  'V-003': [
    {
      name: 'Reza Karimi',
      role: 'Account Manager',
      email: 'rk@sigmadata.ai',
      phone: '+1 512 555 0144',
    },
  ],
  'V-004': [
    {
      name: 'Janelle Kowalski',
      role: 'Account Manager',
      email: 'j.kowalski@helios.print',
      phone: '+1 416 555 0119',
    },
  ],
};

export const CONTRACTS: Readonly<Record<string, readonly Contract[]>> = {
  'V-001': [
    {
      id: 'C-2024-118',
      title: 'Master Services Agreement',
      value: 4_200_000,
      currency: 'USD',
      start: '2024-01-01',
      end: '2026-12-31',
      status: 'ACTIVE',
    },
    {
      id: 'C-2024-119',
      title: 'Data Processing Addendum',
      value: 0,
      currency: 'USD',
      start: '2024-01-01',
      end: '2026-12-31',
      status: 'ACTIVE',
    },
  ],
  'V-002': [
    {
      id: 'C-2023-088',
      title: 'Logistics SOW — North Region',
      value: 1_900_000,
      currency: 'USD',
      start: '2023-07-01',
      end: '2025-06-30',
      status: 'ACTIVE',
    },
  ],
  'V-003': [
    {
      id: 'C-2025-012',
      title: 'Analytics Platform License',
      value: 2_700_000,
      currency: 'USD',
      start: '2025-01-01',
      end: '2027-12-31',
      status: 'ACTIVE',
    },
  ],
};

export const TEAMS: readonly string[] = [
  'Billing Ops',
  'Procurement',
  'Tax & Compliance',
  'Vendor Relations',
  'Engineering Liaison',
  'Legal',
];

export const INTENTS: readonly string[] = [
  'Invoice clarification',
  'Payment status inquiry',
  'Tax form W‑9',
  'Contract amendment',
  'PO confirmation',
  'Banking detail change',
  'Statement reconciliation',
  'Onboarding update',
  'Service credit request',
  'Insurance certificate',
];

const SUBJECTS: readonly string[] = [
  'Re: Invoice INV‑88241 short paid by $1,847',
  'Updated banking details — please confirm receipt',
  'Q1 2026 statement does not match remittance',
  'PO 4419821 — partial shipment, do we re‑bill?',
  'W‑9 expired, need updated copy on file',
  'Amendment #3 to MSA — counter‑signature pending',
  'Service credit owed for Feb 14 outage',
  'Certificate of insurance expiring May 1',
  'Duplicate invoice INV‑88112 / INV‑88114 — please void one',
  'Change of remit‑to address',
  'Annual rate increase notice — clarification',
  'Past‑due reminder for already‑paid INV‑87900',
  'Diversity certification — NAICS update',
  '1099 issuance question for FY2025',
  'Onboarding form — section 4 unclear',
  'Portal access — locked out for 3 days',
  'Sales tax exemption certificate refresh',
  'Late fee waiver request — March cycle',
  'ACH details mismatch — vendor master vs. invoice',
  'Cancellation of standing PO 4418772',
];

const PATHS: readonly ('A' | 'B' | 'C')[] = ['A', 'A', 'A', 'A', 'B', 'B', 'B', 'C', 'C', 'B'];
const STATUSES: readonly string[] = [
  'RESOLVED',
  'DELIVERING',
  'DRAFTING',
  'ROUTING',
  'ANALYZING',
  'AWAITING_RESOLUTION',
  'PAUSED',
  'RESOLVED',
  'RESOLVED',
  'DRAFTING',
];
const PATH_B_TEAMS: readonly string[] = ['Billing Ops', 'Procurement', 'Tax & Compliance'];

export const NOW_ISO = '2026-04-28T14:23:00Z';

export const QUERIES: readonly Query[] = (() => {
  const now = new Date(NOW_ISO);
  const out: Query[] = [];
  for (let i = 0; i < 56; i++) {
    const v = VENDORS[i % VENDORS.length]!;
    const path = PATHS[i % PATHS.length]!;
    const status =
      i < 4
        ? (['DRAFTING', 'ROUTING', 'ANALYZING', 'PAUSED'] as const)[i]!
        : STATUSES[i % STATUSES.length]!;
    const conf = path === 'C' ? 0.42 + (i % 7) * 0.05 : 0.86 + (i % 9) * 0.012;
    const rec = new Date(now.getTime() - i * 1000 * 60 * (37 + (i % 11) * 13));
    const sla_pct = path === 'A' ? null : Math.min(99, 18 + ((i * 7) % 90));
    out.push({
      query_id: `VQ-2026-${String(1842 - i).padStart(4, '0')}`,
      correlation_id: `corr_${(0xa3f12c + i * 1117).toString(16)}`,
      execution_id: `exec_${(0xb91240 + i * 4231).toString(16)}`,
      source: i % 4 === 0 ? 'portal' : 'email',
      subject: SUBJECTS[i % SUBJECTS.length]!,
      vendor_id: v.vendor_id,
      vendor_name: v.name,
      vendor_tier: v.tier,
      priority: i % 13 === 0 ? 'P1' : i % 5 === 0 ? 'P2' : 'P3',
      status,
      processing_path: path,
      assigned_team:
        path === 'B'
          ? PATH_B_TEAMS[i % 3]!
          : path === 'C'
            ? 'Triage Reviewer'
            : '—',
      intent: INTENTS[i % INTENTS.length]!,
      confidence: Number(conf.toFixed(3)),
      kb_match:
        path === 'A'
          ? Number((0.81 + (i % 9) * 0.012).toFixed(2))
          : path === 'B'
            ? Number((0.42 + (i % 9) * 0.03).toFixed(2))
            : Number((0.31 + (i % 9) * 0.02).toFixed(2)),
      received_at: rec.toISOString(),
      sla_pct,
      sla_deadline_min: sla_pct ? Math.round((100 - sla_pct) * 1.4) : null,
      attachments: i % 3 === 0 ? Math.max(1, i % 4) : 0,
      ticket_id: path === 'B' ? `INC-${String(2_140_000 + i).padStart(7, '0')}` : null,
      reopened: i % 17 === 0,
    });
  }
  return out;
})();

export const TREND_30D: readonly VolumeRow[] = (() => {
  const out: VolumeRow[] = [];
  for (let i = 29; i >= 0; i--) {
    const d = new Date(2026, 3, 28 - i);
    const base = 38 + Math.round(14 * Math.sin(i / 4)) + (i % 7 === 0 ? -8 : 0);
    out.push({
      date: d.toISOString().slice(5, 10),
      A: Math.max(8, Math.round(base * 0.62 + (i % 5))),
      B: Math.max(4, Math.round(base * 0.27 + (i % 3))),
      C: Math.max(2, Math.round(base * 0.11 + (i % 2))),
      received: base + 2,
    });
  }
  return out;
})();

export const HOURLY_24H: readonly HourlyRow[] = Array.from({ length: 24 }, (_, h) => ({
  hour: String(h).padStart(2, '0'),
  ingested: 4 + Math.round(8 * Math.abs(Math.sin((h - 8) / 3))) + (h > 8 && h < 18 ? 6 : 0),
  resolved: 3 + Math.round(7 * Math.abs(Math.sin((h - 9) / 3))) + (h > 9 && h < 19 ? 5 : 0),
}));

export const CONFIDENCE_HIST: readonly ConfidenceBand[] = [
  { band: '0.0–0.2', n: 4 },
  { band: '0.2–0.4', n: 11 },
  { band: '0.4–0.6', n: 18 },
  { band: '0.6–0.8', n: 27 },
  { band: '0.8–0.9', n: 64 },
  { band: '0.9–1.0', n: 142 },
];

export const SLA_BY_TEAM: readonly TeamSla[] = [
  { team: 'Billing Ops', on_time: 84, breached: 7 },
  { team: 'Procurement', on_time: 41, breached: 2 },
  { team: 'Tax & Compliance', on_time: 22, breached: 4 },
  { team: 'Vendor Relations', on_time: 38, breached: 1 },
  { team: 'Eng. Liaison', on_time: 14, breached: 0 },
  { team: 'Legal', on_time: 9, breached: 1 },
];

export const TOP_INTENTS: readonly IntentBucket[] = [
  { intent: 'Invoice clarification', n: 89 },
  { intent: 'Payment status', n: 64 },
  { intent: 'Statement reconciliation', n: 41 },
  { intent: 'Banking detail change', n: 28 },
  { intent: 'Tax form W‑9', n: 22 },
  { intent: 'PO confirmation', n: 19 },
];

export const KB_ARTICLES: readonly KbArticle[] = [
  {
    id: 'kb_001',
    title: 'Standard remittance address by region',
    last_updated: '2026-04-12',
    uses_30d: 142,
    hit_rate: 0.94,
  },
  {
    id: 'kb_002',
    title: 'How to interpret short‑pay deductions on remittance',
    last_updated: '2026-03-28',
    uses_30d: 88,
    hit_rate: 0.81,
  },
  {
    id: 'kb_003',
    title: 'Updated banking details — verification protocol',
    last_updated: '2026-04-22',
    uses_30d: 64,
    hit_rate: 0.97,
  },
  {
    id: 'kb_004',
    title: 'W‑9 collection workflow (US vendors)',
    last_updated: '2026-02-11',
    uses_30d: 51,
    hit_rate: 0.92,
  },
  {
    id: 'kb_005',
    title: 'MSA amendment counter‑signature SLA',
    last_updated: '2026-01-19',
    uses_30d: 18,
    hit_rate: 0.74,
  },
  {
    id: 'kb_006',
    title: 'Late fee waiver — eligibility matrix',
    last_updated: '2026-04-02',
    uses_30d: 33,
    hit_rate: 0.88,
  },
  {
    id: 'kb_007',
    title: 'Service credit calculation methodology',
    last_updated: '2025-11-30',
    uses_30d: 22,
    hit_rate: 0.79,
  },
  {
    id: 'kb_008',
    title: 'Diversity certification — NAICS code refresh',
    last_updated: '2026-03-04',
    uses_30d: 9,
    hit_rate: 0.66,
  },
  {
    id: 'kb_009',
    title: 'Insurance certificate renewal cadence',
    last_updated: '2026-04-15',
    uses_30d: 27,
    hit_rate: 0.91,
  },
  {
    id: 'kb_010',
    title: 'Portal lockout — self‑service unlock procedure',
    last_updated: '2026-04-20',
    uses_30d: 14,
    hit_rate: 0.83,
  },
  {
    id: 'kb_011',
    title: '1099 issuance — fiscal year cutoffs',
    last_updated: '2025-12-15',
    uses_30d: 6,
    hit_rate: 0.71,
  },
  {
    id: 'kb_012',
    title: 'Standing PO cancellation — required approvers',
    last_updated: '2026-02-28',
    uses_30d: 11,
    hit_rate: 0.77,
  },
];

export const INTEGRATIONS: readonly Integration[] = [
  {
    name: 'Amazon Bedrock',
    kind: 'LLM',
    status: 'healthy',
    latency_ms: 612,
    region: 'us-east-1',
    note: 'claude-sonnet-3.5 + titan-embed-v2',
  },
  {
    name: 'Amazon RDS for PostgreSQL',
    kind: 'Database',
    status: 'healthy',
    latency_ms: 14,
    region: 'us-east-1',
    note: 'pgvector 0.7.0 · 6 schemas',
  },
  {
    name: 'Amazon S3',
    kind: 'Object Storage',
    status: 'healthy',
    latency_ms: 41,
    region: 'us-east-1',
    note: 'vqms-data-store · 1.84 TB',
  },
  {
    name: 'Amazon SQS',
    kind: 'Queue',
    status: 'healthy',
    latency_ms: 22,
    region: 'us-east-1',
    note: 'intake + DLQ · 3 visible',
  },
  {
    name: 'Amazon EventBridge',
    kind: 'Events',
    status: 'healthy',
    latency_ms: 18,
    region: 'us-east-1',
    note: '20 event types',
  },
  {
    name: 'Amazon Textract',
    kind: 'OCR',
    status: 'healthy',
    latency_ms: 1850,
    region: 'us-east-1',
    note: 'async jobs only',
  },
  {
    name: 'Microsoft Graph API',
    kind: 'Email Source',
    status: 'degraded',
    latency_ms: 2240,
    region: 'global',
    note: 'throttling on /messages — 429s last 14m',
  },
  {
    name: 'Salesforce CRM',
    kind: 'Vendor Master',
    status: 'healthy',
    latency_ms: 380,
    region: '—',
    note: 'Vendor_Account__c · 8 cached',
  },
  {
    name: 'ServiceNow ITSM',
    kind: 'Ticketing',
    status: 'healthy',
    latency_ms: 491,
    region: '—',
    note: 'incident table · webhook live',
  },
  {
    name: 'OpenAI (fallback)',
    kind: 'LLM',
    status: 'standby',
    latency_ms: null,
    region: '—',
    note: 'GPT-4o · used 0× in 24h',
  },
];

export const QUEUES: readonly Queue[] = [
  {
    name: 'vqms-email-intake-queue',
    visible: 3,
    in_flight: 1,
    dlq: 0,
    oldest_age_s: 7,
    throughput_1m: 14,
  },
  {
    name: 'vqms-query-intake-queue',
    visible: 0,
    in_flight: 0,
    dlq: 0,
    oldest_age_s: 0,
    throughput_1m: 6,
  },
  { name: 'vqms-email-intake-dlq', visible: 0, in_flight: 0, dlq: 0, oldest_age_s: 0, throughput_1m: 0 },
  {
    name: 'vqms-query-intake-dlq',
    visible: 1,
    in_flight: 0,
    dlq: 1,
    oldest_age_s: 4_120,
    throughput_1m: 0,
  },
];

export const EMAIL_PIPELINE: readonly PipelineStage[] = [
  { stage: 'MS Graph webhook', in: 218, out: 218, errors: 0, median_ms: 84 },
  { stage: 'Relevance filter', in: 218, out: 187, errors: 0, median_ms: 31 },
  { stage: 'Attachment processor', in: 187, out: 184, errors: 3, median_ms: 1240 },
  { stage: 'Vendor identifier', in: 184, out: 184, errors: 0, median_ms: 96 },
  { stage: 'Thread correlator', in: 184, out: 184, errors: 0, median_ms: 22 },
  { stage: 'Persist + SQS enqueue', in: 184, out: 184, errors: 0, median_ms: 51 },
];

export const RECENT_INGEST: readonly {
  ts: string;
  from: string;
  subject: string;
  vendor: string;
  outcome: 'enqueued' | 'filtered' | 'ocr' | 'error';
  lat: number;
}[] = [
  {
    ts: '14:22:51',
    from: 'billing@cloudwave.io',
    subject: 'Re: Invoice INV-88241 short paid by $1,847',
    vendor: 'V-001',
    outcome: 'enqueued',
    lat: 142,
  },
  {
    ts: '14:21:38',
    from: 'ops@northwindlog.com',
    subject: 'Q1 2026 statement does not match remittance',
    vendor: 'V-002',
    outcome: 'enqueued',
    lat: 167,
  },
  {
    ts: '14:20:14',
    from: 'noreply@mailchimp.com',
    subject: 'Your weekly newsletter is here',
    vendor: '—',
    outcome: 'filtered',
    lat: 28,
  },
  {
    ts: '14:19:02',
    from: 'rk@sigmadata.ai',
    subject: 'PO 4419821 partial shipment, do we re-bill?',
    vendor: 'V-003',
    outcome: 'enqueued',
    lat: 184,
  },
  {
    ts: '14:17:44',
    from: 'billing@helios.print',
    subject: 'Scanned invoice — please process',
    vendor: 'V-004',
    outcome: 'ocr',
    lat: 1840,
  },
  {
    ts: '14:16:33',
    from: 'g.lindqvist@northwindlog.com',
    subject: 'Updated banking details — confirm',
    vendor: 'V-002',
    outcome: 'enqueued',
    lat: 156,
  },
  {
    ts: '14:15:12',
    from: 'unknown@gmail.com',
    subject: 'Hi, are you the right person?',
    vendor: '—',
    outcome: 'filtered',
    lat: 33,
  },
  {
    ts: '14:13:08',
    from: 'j.kowalski@helios.print',
    subject: 'W-9 expired, need updated copy on file',
    vendor: 'V-004',
    outcome: 'enqueued',
    lat: 138,
  },
];

export const AUDIT_LOG: readonly AuditEntry[] = [
  {
    ts: '2026-04-28 14:21:08',
    actor: 'system',
    action: 'Path A resolution delivered',
    target: 'VQ-2026-1842',
    note: 'kb_001 · conf 0.93',
  },
  {
    ts: '2026-04-28 14:19:42',
    actor: 'n.shah@hexaware.com',
    action: 'Triage decision — corrected intent',
    target: 'VQ-2026-1838',
    note: '→ Banking detail change',
  },
  {
    ts: '2026-04-28 14:18:11',
    actor: 'system',
    action: 'SLA warning fired (70%)',
    target: 'VQ-2026-1816',
    note: 'Billing Ops · 14m left',
  },
  {
    ts: '2026-04-28 14:15:33',
    actor: 'k.tanaka@hexaware.com',
    action: 'Draft approved',
    target: 'VQ-2026-1834',
    note: 'Path B resolution-from-notes',
  },
  {
    ts: '2026-04-28 14:12:07',
    actor: 'system',
    action: 'Quality Gate failed — redraft',
    target: 'VQ-2026-1839',
    note: 'missing_attribution',
  },
  {
    ts: '2026-04-28 14:09:51',
    actor: 'system',
    action: 'ServiceNow webhook RESOLVED',
    target: 'INC-2140017',
    note: '→ Step 15 enqueued',
  },
  {
    ts: '2026-04-28 14:04:18',
    actor: 'j.okafor@hexaware.com',
    action: 'Bulk reroute (12)',
    target: '—',
    note: 'Procurement → Billing Ops',
  },
  {
    ts: '2026-04-28 14:01:02',
    actor: 'system',
    action: 'Episodic memory written',
    target: 'VQ-2026-1830',
    note: 'vendor V-002 · invoice clarification',
  },
  {
    ts: '2026-04-28 13:58:44',
    actor: 'system',
    action: 'Path C package persisted',
    target: 'VQ-2026-1837',
    note: 'conf 0.49',
  },
  {
    ts: '2026-04-28 13:54:22',
    actor: 'admin@hexaware.com',
    action: 'Feature flag toggled',
    target: 'step15_resolution_from_notes',
    note: 'OFF → ON',
  },
];

export const USERS: readonly UserRow[] = [
  {
    email: 'admin@hexaware.com',
    name: 'Anika Verma',
    role: 'Admin',
    last_active: '2m',
    status: 'online',
  },
  {
    email: 'n.shah@hexaware.com',
    name: 'Niraj Shah',
    role: 'Reviewer',
    last_active: 'now',
    status: 'online',
  },
  {
    email: 'k.tanaka@hexaware.com',
    name: 'Kenji Tanaka',
    role: 'Admin',
    last_active: '8m',
    status: 'online',
  },
  {
    email: 'j.okafor@hexaware.com',
    name: 'Jide Okafor',
    role: 'Admin',
    last_active: '21m',
    status: 'away',
  },
  {
    email: 'p.barros@hexaware.com',
    name: 'Paula Barros',
    role: 'Reviewer',
    last_active: '2h',
    status: 'offline',
  },
  {
    email: 'h.lefevre@hexaware.com',
    name: 'Hugo Lefèvre',
    role: 'Reviewer',
    last_active: 'now',
    status: 'online',
  },
  {
    email: 'vendor@cloudwave.io',
    name: 'Marcus Holloway',
    role: 'Vendor',
    last_active: '1d',
    status: 'offline',
  },
];

export const FEATURE_FLAGS: readonly FeatureFlag[] = [
  {
    key: 'step15_resolution_from_notes',
    on: true,
    scope: 'global',
    changed: '2026-04-28 13:54',
  },
  { key: 'openai_fallback', on: true, scope: 'global', changed: '2026-04-22 09:11' },
  { key: 'auto_close_after_window', on: true, scope: 'global', changed: '2026-04-08 12:00' },
  { key: 'reviewer_copilot_sse', on: true, scope: 'reviewer', changed: '2026-04-15 17:42' },
  { key: 'bulk_reroute', on: true, scope: 'vendor_manager', changed: '2026-03-30 10:18' },
  { key: 'vendor_self_serve_kb', on: false, scope: 'vendor', changed: '2026-02-12 11:01' },
  { key: 'amazon_bedrock_streaming', on: false, scope: 'global', changed: '—' },
];

export const SAMPLE_THREAD: readonly ThreadMessage[] = [
  {
    direction: 'inbound',
    from: 'billing@cloudwave.io',
    to: 'vendor-support@hexaware.com',
    ts: '2026-04-28 11:14',
    subject: 'Re: Invoice INV-88241 short paid by $1,847',
    body: 'Hi team — we received your remittance for INV-88241 but it short‑paid by $1,847.00. Could you confirm the deduction code and provide the netted document? Our records show this should have paid in full at $24,310.50. Attaching the original invoice and the remittance advice.\n\nThanks,\nMarcus Holloway\nCloudwave Hosting · Account Manager',
    attachments: [
      { name: 'INV-88241.pdf', size: '184 KB' },
      { name: 'Remittance-2026-04-22.pdf', size: '62 KB' },
    ],
  },
  {
    direction: 'system',
    ts: '2026-04-28 11:14:08',
    note: "Email parsed · vendor identified V-001 (Cloudwave Hosting) via Salesforce match · attachments OCR'd via Amazon Textract",
  },
  {
    direction: 'system',
    ts: '2026-04-28 11:14:22',
    note: 'Query analysis · intent=Invoice clarification · confidence=0.93 · KB best match kb_002 cosine=0.87 → Path A',
  },
];

export const AI_SUGGESTED = `Hi Marcus,

Thanks for the detail. The $1,847.00 short‑pay on INV-88241 corresponds to deduction code SP‑D‑412 (early‑payment discount applied per your January 2026 amendment). The netted document is attached as INV-88241‑NET.pdf.

Summary of the math:
  Original invoice         $24,310.50
  Early‑payment discount   −$ 1,847.00  (7.6% per Amendment §3.2)
  Remitted total           $22,463.50

If your records reflect a different posting, let us know the AR document number on your side and we'll reconcile.

Best,
Hexaware Vendor Support`;

export const SOURCES_USED: readonly SourceUsed[] = [
  {
    kb_id: 'kb_002',
    title: 'How to interpret short‑pay deductions on remittance',
    cosine: 0.87,
  },
  { kb_id: 'kb_001', title: 'Standard remittance address by region', cosine: 0.74 },
];

export function relativeTime(iso: string): string {
  const now = new Date(NOW_ISO);
  const ms = now.getTime() - new Date(iso).getTime();
  const m = Math.round(ms / 60_000);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
