// Mail / Email management data — types + mock data for the 3-pane unified inbox.
// Field shape mirrors intake.email_messages, intake.email_attachments,
// workflow.draft_responses, audit.action_log. UI-only fields are prefixed with `_`.

import { VENDORS } from './mock-data';
import type { ProcessingPath, TierName } from './models';

export type MailDirection = 'inbound' | 'outbound';
export type MailStatus = 'unread' | 'read' | 'sent' | 'draft';
export type MailDraftType = 'RESOLUTION' | 'ACKNOWLEDGMENT';
export type MailFolderId =
  | 'all'
  | 'unread'
  | 'inbox'
  | 'sent'
  | 'drafts'
  | 'awaiting'
  | 'ai_suggested'
  | 'flagged'
  | 'archived'
  | 'spam';

export interface MailFolder {
  readonly id: MailFolderId;
  readonly label: string;
  readonly icon: string;
}

export interface MailAttachment {
  readonly attachment_id: string;
  readonly filename: string;
  readonly size_bytes: number;
  readonly mime_type: string;
  readonly s3_key: string;
}

export interface MailThread {
  readonly message_id: string;
  readonly conversation_id: string;
  readonly in_reply_to: string | null;
  readonly from_address: string;
  readonly from_name: string;
  readonly to_addresses: readonly string[];
  readonly cc_addresses: readonly string[];
  readonly subject: string;
  readonly body_text: string;
  readonly body_html: string | null;
  readonly received_at: string;
  readonly ingestion_status: string;
  readonly processed_at: string;
  readonly attachments: readonly MailAttachment[];
  readonly query_id: string;
  readonly processing_path: ProcessingPath;
  readonly confidence_score: number;
  readonly assigned_team: string | null;
  readonly ticket_id: string | null;
  readonly vendor_id: string;
  readonly vendor_name: string;
  readonly vendor_tier: TierName;
  readonly _direction: MailDirection;
  readonly _status: MailStatus;
  readonly _flagged: boolean;
  readonly _has_ai_draft: boolean;
  readonly _sla_pct: number | null;
}

export interface MailDraftSource {
  readonly kb_id: string;
  readonly title: string;
  readonly cosine: number;
}

export interface MailQualityGate {
  readonly passed: boolean;
  readonly checks_passed: number;
  readonly checks_failed: number;
  readonly failed?: readonly string[];
}

export interface MailAiDraft {
  readonly draft_id: string;
  readonly draft_type: MailDraftType;
  readonly confidence: number;
  readonly body_text: string;
  readonly sources: readonly MailDraftSource[];
  readonly quality_gate: MailQualityGate;
  readonly generated_at: string;
}

export interface MailHistoryMsg {
  readonly from: string;
  readonly from_name: string;
  readonly to: readonly string[];
  readonly ts: string;
  readonly subject: string;
  readonly snippet: string;
  readonly body?: string;
  readonly attachments?: readonly string[];
  readonly collapsed: boolean;
}

export interface MailAuditEntry {
  readonly ts: string;
  readonly actor: string;
  readonly action: string;
}

export interface MailInternalNote {
  readonly author: string;
  readonly ts: string;
  readonly text: string;
}

export interface MailSyncStatus {
  readonly last_sync_seconds_ago: number;
  readonly next_poll_seconds: number;
  readonly graph_status: 'healthy' | 'degraded' | 'down' | 'standby';
  readonly graph_note: string;
  readonly sqs_visible: number;
  readonly sqs_in_flight: number;
  readonly sqs_dlq: number;
}

export interface MailTemplate {
  readonly id: string;
  readonly name: string;
  readonly category: string;
}

export const MAIL_FOLDERS: readonly MailFolder[] = [
  { id: 'all', label: 'All Mail', icon: 'mails' },
  { id: 'unread', label: 'Unread', icon: 'mail' },
  { id: 'inbox', label: 'Inbox', icon: 'inbox' },
  { id: 'sent', label: 'Sent', icon: 'send' },
  { id: 'drafts', label: 'Drafts', icon: 'file-edit' },
  { id: 'awaiting', label: 'Awaiting reply', icon: 'clock' },
  { id: 'ai_suggested', label: 'AI‑suggested', icon: 'sparkles' },
  { id: 'flagged', label: 'Flagged', icon: 'flag' },
  { id: 'archived', label: 'Archived', icon: 'archive' },
  { id: 'spam', label: 'Filtered out', icon: 'ban' },
];

const MAIL_BODIES: Readonly<Record<string, string>> = {
  short_pay: `Hi team,

We received your remittance for INV-88241 but it short‑paid by $1,847.00. Could you confirm the deduction code and provide the netted document? Our records show this should have paid in full at $24,310.50.

Attaching the original invoice and the remittance advice.

Thanks,
Marcus Holloway
Cloudwave Hosting · Account Manager
+1 206 555 0188`,
  banking: `Hello,

Effective May 1, our bank details have changed. Please update your records:

  Bank:        First Continental
  Routing:     026009593
  Account:     ••••‑••‑4419
  SWIFT:       FCONUS33

Confirmation of receipt would be appreciated. We will continue to monitor inbound payments to the legacy account through May 31 as a safeguard.

Best regards,
Greta Lindqvist
Northwind Logistics`,
  recon: `Team —

Our Q1 2026 statement shows $112,408.00 outstanding but our remittance ledger reflects $108,200.00 paid in full. The $4,208.00 delta appears across three invoices (INV‑87904, INV‑87918, INV‑87931). Can you reconcile and re‑issue the statement?

Spreadsheet attached.

— Reza Karimi, Sigma Data Labs`,
  partial: `PO 4419821 shipped in two parts (60% on Apr 14, 40% on Apr 22). Should we re‑bill against the same PO line items, or do you need split invoices? Following the convention you used last quarter unless we hear back.

Janelle Kowalski, Helios Print Co.`,
  w9: `Our W‑9 on file with your AP team expired in February. Please find the updated 2026 copy attached, signed by our controller. Confirm receipt at your convenience.

Thanks,
Hugo Lefèvre
Bramble & Hart LLP`,
  amendment: `Counter‑signature still pending on Amendment #3. Legal sent over the redline 11 days ago. SLA on contract amendments is 5 business days per our MSA — please advise.

Reza Karimi
Sigma Data Labs`,
  credit: `Per our SLA, the Feb 14 outage exceeded the 4‑hour resolution window by 2h 18m, qualifying for a service credit of 7.5% on the affected month. Please apply against May invoicing or remit separately.

Marcus Holloway
Cloudwave Hosting`,
  insurance: `Our certificate of insurance expires May 1. Renewed COI attached, effective through May 1, 2027. Carrier and coverage limits unchanged.

Owen Adesina, Northwind Logistics`,
  duplicate: `INV-88112 and INV-88114 appear to be duplicates of the same shipment (PO 4418901). Both were posted on Apr 18 with identical line items. Please void INV-88114.

Greta Lindqvist`,
  remit: `Please update remit‑to address for all future payments:

  Yamasaki Hardware Co., Ltd.
  3‑15‑8 Umeda, Kita‑ku
  Osaka 530‑0001, Japan

Effective immediately. ACH details unchanged.

Tomohiro Yamasaki`,
  rate: `The annual rate increase notice we received references a 6.4% adjustment but our MSA Section 7.3 caps yearly escalation at CPI+1% (currently 4.2%). Could you clarify how 6.4% was derived?

Reza Karimi, Sigma Data Labs`,
  paid: `We received a past‑due reminder this morning for INV-87900, but our records show this was paid via ACH on Apr 11 (ref #FT2026041100871). Attaching wire confirmation.

— Janelle, Helios Print`,
};

interface MailSeed {
  readonly vendor: string;
  readonly contact: string;
  readonly email: string;
  readonly subject: string;
  readonly body: keyof typeof MAIL_BODIES;
  readonly path: ProcessingPath;
  readonly conf: number;
  readonly query_id: string;
  readonly path_team: string | null;
  readonly sla: number | null;
  readonly attach: readonly string[];
  readonly flagged: boolean;
  readonly has_ai: boolean;
  readonly status: MailStatus;
  readonly dir: MailDirection;
}

const SEEDS: readonly MailSeed[] = [
  { vendor: 'V-001', contact: 'Marcus Holloway', email: 'billing@cloudwave.io', subject: 'Re: Invoice INV‑88241 short paid by $1,847', body: 'short_pay', path: 'A', conf: 0.93, query_id: 'VQ-2026-1842', path_team: null, sla: 22, attach: ['INV-88241.pdf', 'Remittance-2026-04-22.pdf'], flagged: false, has_ai: true, status: 'unread', dir: 'inbound' },
  { vendor: 'V-002', contact: 'Greta Lindqvist', email: 'g.lindqvist@northwindlog.com', subject: 'Updated banking details — please confirm receipt', body: 'banking', path: 'C', conf: 0.49, query_id: 'VQ-2026-1841', path_team: 'Triage Reviewer', sla: 71, attach: ['Bank-Letter-Northwind.pdf'], flagged: true, has_ai: true, status: 'unread', dir: 'inbound' },
  { vendor: 'V-003', contact: 'Reza Karimi', email: 'rk@sigmadata.ai', subject: 'Q1 2026 statement does not match remittance', body: 'recon', path: 'B', conf: 0.88, query_id: 'VQ-2026-1840', path_team: 'Billing Ops', sla: 48, attach: ['Q1-2026-Recon.xlsx'], flagged: false, has_ai: false, status: 'read', dir: 'inbound' },
  { vendor: 'V-004', contact: 'Janelle Kowalski', email: 'j.kowalski@helios.print', subject: 'PO 4419821 — partial shipment, do we re‑bill?', body: 'partial', path: 'B', conf: 0.86, query_id: 'VQ-2026-1839', path_team: 'Procurement', sla: 92, attach: [], flagged: false, has_ai: true, status: 'read', dir: 'inbound' },
  { vendor: 'V-005', contact: 'Hugo Lefèvre', email: 'h.lefevre@bramblehart.com', subject: 'W‑9 expired, need updated copy on file', body: 'w9', path: 'A', conf: 0.91, query_id: 'VQ-2026-1838', path_team: null, sla: 8, attach: ['W9-2026-Bramble.pdf'], flagged: false, has_ai: true, status: 'read', dir: 'inbound' },
  { vendor: 'V-003', contact: 'Reza Karimi', email: 'rk@sigmadata.ai', subject: 'Amendment #3 to MSA — counter‑signature pending', body: 'amendment', path: 'B', conf: 0.87, query_id: 'VQ-2026-1837', path_team: 'Legal', sla: 96, attach: [], flagged: true, has_ai: false, status: 'read', dir: 'inbound' },
  { vendor: 'V-001', contact: 'Marcus Holloway', email: 'm.holloway@cloudwave.io', subject: 'Service credit owed for Feb 14 outage', body: 'credit', path: 'B', conf: 0.84, query_id: 'VQ-2026-1836', path_team: 'Billing Ops', sla: 38, attach: ['SLA-breach-log-Feb14.pdf'], flagged: false, has_ai: true, status: 'unread', dir: 'inbound' },
  { vendor: 'V-002', contact: 'Owen Adesina', email: 'ops@northwindlog.com', subject: 'Certificate of insurance expiring May 1', body: 'insurance', path: 'A', conf: 0.95, query_id: 'VQ-2026-1835', path_team: null, sla: 12, attach: ['COI-Northwind-2027.pdf'], flagged: false, has_ai: true, status: 'read', dir: 'inbound' },
  { vendor: 'V-002', contact: 'Greta Lindqvist', email: 'g.lindqvist@northwindlog.com', subject: 'Duplicate invoice INV‑88112 / INV‑88114 — please void one', body: 'duplicate', path: 'A', conf: 0.92, query_id: 'VQ-2026-1834', path_team: null, sla: 18, attach: [], flagged: false, has_ai: true, status: 'read', dir: 'inbound' },
  { vendor: 'V-006', contact: 'Tomohiro Yamasaki', email: 't.yamasaki@yamasaki.co.jp', subject: 'Change of remit‑to address', body: 'remit', path: 'A', conf: 0.89, query_id: 'VQ-2026-1833', path_team: null, sla: 9, attach: [], flagged: false, has_ai: true, status: 'read', dir: 'inbound' },
  { vendor: 'V-003', contact: 'Reza Karimi', email: 'rk@sigmadata.ai', subject: 'Annual rate increase notice — clarification', body: 'rate', path: 'C', conf: 0.51, query_id: 'VQ-2026-1832', path_team: 'Triage Reviewer', sla: 64, attach: ['MSA-Section-7.3-excerpt.pdf'], flagged: false, has_ai: true, status: 'unread', dir: 'inbound' },
  { vendor: 'V-004', contact: 'Janelle Kowalski', email: 'j.kowalski@helios.print', subject: 'Past‑due reminder for already‑paid INV‑87900', body: 'paid', path: 'A', conf: 0.94, query_id: 'VQ-2026-1831', path_team: null, sla: 14, attach: ['FT2026041100871.pdf'], flagged: false, has_ai: true, status: 'read', dir: 'inbound' },
  { vendor: 'V-001', contact: 'Anika Verma', email: 'vendor-support@hexaware.com', subject: 'Re: Insurance certificate renewal — confirmed', body: 'insurance', path: 'A', conf: 0.95, query_id: 'VQ-2026-1835', path_team: null, sla: null, attach: [], flagged: false, has_ai: false, status: 'sent', dir: 'outbound' },
  { vendor: 'V-005', contact: 'Anika Verma', email: 'vendor-support@hexaware.com', subject: 'Re: W‑9 expired, need updated copy on file (draft)', body: 'w9', path: 'A', conf: 0.91, query_id: 'VQ-2026-1838', path_team: null, sla: null, attach: [], flagged: false, has_ai: false, status: 'draft', dir: 'outbound' },
];

const NOW = new Date('2026-04-28T14:23:00Z').getTime();

function vendorLookup(vendorId: string): { name: string; tier: TierName } {
  const v = VENDORS.find((x) => x.vendor_id === vendorId);
  return { name: v?.name ?? '—', tier: (v?.tier as TierName) ?? 'SILVER' };
}

function mimeFor(filename: string): string {
  if (filename.endsWith('.pdf')) return 'application/pdf';
  if (filename.endsWith('.xlsx')) return 'application/vnd.openxmlformats';
  return 'application/octet-stream';
}

export const MAIL_THREADS: readonly MailThread[] = SEEDS.map((s, i) => {
  const recMs = NOW - i * 1000 * 60 * (12 + (i % 7) * 31);
  const rec = new Date(recMs);
  const v = vendorLookup(s.vendor);
  return {
    message_id: `<AAMkAG${(0xab12 + i * 211).toString(16)}@graph.microsoft.com>`,
    conversation_id: `conv_${(0xc92a + Math.floor(i / 2) * 41).toString(16)}`,
    in_reply_to:
      i % 3 === 0
        ? `<AAMkAG${(0xab12 + (i - 1) * 211).toString(16)}@graph.microsoft.com>`
        : null,
    from_address: s.email,
    from_name: s.contact,
    to_addresses:
      s.dir === 'inbound' ? ['vendor-support@hexaware.com'] : [s.email],
    cc_addresses: i % 5 === 0 ? ['ap-team@hexaware.com'] : [],
    subject: s.subject,
    body_text: MAIL_BODIES[s.body] ?? '(empty)',
    body_html: null,
    received_at: rec.toISOString(),
    ingestion_status: 'PROCESSED',
    processed_at: new Date(rec.getTime() + 4200).toISOString(),
    attachments: s.attach.map((name, k) => ({
      attachment_id: `att_${i}_${k}`,
      filename: name,
      size_bytes: 60_000 + k * 41_000 + i * 7_000,
      mime_type: mimeFor(name),
      s3_key: `s3://vqms-data-store/inbound-emails/${rec.toISOString().slice(0, 10)}/${s.vendor}/${name}`,
    })),
    query_id: s.query_id,
    processing_path: s.path,
    confidence_score: s.conf,
    assigned_team: s.path_team,
    ticket_id: s.path === 'B' ? `INC-${String(2_140_000 + i).padStart(7, '0')}` : null,
    vendor_id: s.vendor,
    vendor_name: v.name,
    vendor_tier: v.tier,
    _direction: s.dir,
    _status: s.status,
    _flagged: s.flagged,
    _has_ai_draft: s.has_ai,
    _sla_pct: s.sla,
  } satisfies MailThread;
});

const FIRST_ID = MAIL_THREADS[0]!.message_id;
const SECOND_ID = MAIL_THREADS[1]!.message_id;
const SEVENTH_ID = MAIL_THREADS[6]!.message_id;

export const MAIL_AI_DRAFTS: Readonly<Record<string, MailAiDraft>> = {
  [FIRST_ID]: {
    draft_id: 'drf_a1b2c3',
    draft_type: 'RESOLUTION',
    confidence: 0.93,
    body_text: `Hi Marcus,

Thanks for the detail. The $1,847.00 short‑pay on INV‑88241 corresponds to deduction code SP‑D‑412 (early‑payment discount applied per your January 2026 amendment). The netted document is attached as INV‑88241‑NET.pdf.

Summary of the math:
  Original invoice         $24,310.50
  Early‑payment discount   −$ 1,847.00  (7.6% per Amendment §3.2)
  Remitted total           $22,463.50

If your records reflect a different posting, share the AR document number on your side and we'll reconcile.

Best,
Hexaware Vendor Support`,
    sources: [
      { kb_id: 'kb_002', title: 'How to interpret short‑pay deductions on remittance', cosine: 0.87 },
      { kb_id: 'kb_001', title: 'Standard remittance address by region', cosine: 0.74 },
    ],
    quality_gate: { passed: true, checks_passed: 7, checks_failed: 0 },
    generated_at: '2026-04-28T11:14:38Z',
  },
  [SECOND_ID]: {
    draft_id: 'drf_d4e5f6',
    draft_type: 'ACKNOWLEDGMENT',
    confidence: 0.49,
    body_text: `Hi Greta,

We've received your bank detail change request. For verification, our updated‑banking‑details protocol requires a second confirmation channel per kb_003.

A reviewer will validate and confirm receipt within 1 business day. No payments to the new account will be issued until verification clears.

Hexaware Vendor Support`,
    sources: [
      { kb_id: 'kb_003', title: 'Updated banking details — verification protocol', cosine: 0.81 },
    ],
    quality_gate: {
      passed: false,
      checks_passed: 5,
      checks_failed: 2,
      failed: ['confidence_below_threshold', 'verification_required'],
    },
    generated_at: '2026-04-28T13:51:02Z',
  },
  [SEVENTH_ID]: {
    draft_id: 'drf_g7h8i9',
    draft_type: 'ACKNOWLEDGMENT',
    confidence: 0.84,
    body_text: `Hi Marcus,

Your service credit request for the Feb 14 outage has been acknowledged and routed to Billing Ops (ticket INC‑2140006). Per our SLA, we'll calculate the eligible credit using the methodology in kb_007 and respond within 2 business days.

Hexaware Vendor Support`,
    sources: [{ kb_id: 'kb_007', title: 'Service credit calculation methodology', cosine: 0.79 }],
    quality_gate: { passed: true, checks_passed: 7, checks_failed: 0 },
    generated_at: '2026-04-28T12:48:11Z',
  },
};

export const MAIL_THREAD_HISTORY: Readonly<Record<string, readonly MailHistoryMsg[]>> = {
  [MAIL_THREADS[0]!.conversation_id]: [
    {
      from: 'billing@cloudwave.io',
      from_name: 'Marcus Holloway',
      to: ['vendor-support@hexaware.com'],
      ts: '2026-04-22T09:14:00Z',
      subject: 'Invoice INV‑88241 — payment received, please confirm',
      snippet: 'Wanted to confirm you received our payment for INV‑88241 last Friday…',
      collapsed: true,
    },
    {
      from: 'vendor-support@hexaware.com',
      from_name: 'Hexaware Vendor Support',
      to: ['billing@cloudwave.io'],
      ts: '2026-04-22T11:02:00Z',
      subject: 'Re: Invoice INV‑88241 — payment received',
      snippet: 'Confirming receipt. Posting to your account today.',
      collapsed: true,
    },
    {
      from: 'billing@cloudwave.io',
      from_name: 'Marcus Holloway',
      to: ['vendor-support@hexaware.com'],
      ts: '2026-04-28T11:14:00Z',
      subject: 'Re: Invoice INV‑88241 short paid by $1,847',
      snippet: MAIL_BODIES['short_pay']!.slice(0, 120),
      body: MAIL_BODIES['short_pay'],
      attachments: ['INV-88241.pdf', 'Remittance-2026-04-22.pdf'],
      collapsed: false,
    },
  ],
};

export const MAIL_AUDIT: Readonly<Record<string, readonly MailAuditEntry[]>> = {
  [FIRST_ID]: [
    { ts: '2026-04-28 11:14:00', actor: 'system', action: 'Email received via Microsoft Graph webhook' },
    { ts: '2026-04-28 11:14:08', actor: 'system', action: 'Vendor identified V‑001 (Cloudwave Hosting) via Salesforce' },
    { ts: '2026-04-28 11:14:14', actor: 'system', action: "Attachments OCR'd via Amazon Textract (2 files)" },
    { ts: '2026-04-28 11:14:22', actor: 'system', action: 'Path A · KB match kb_002 cosine 0.87 · confidence 0.93' },
    { ts: '2026-04-28 11:14:38', actor: 'system', action: 'AI draft generated — Quality Gate: passed (7/7)' },
    { ts: '2026-04-28 14:18:09', actor: 'n.shah@hexaware.com', action: 'Viewed message' },
  ],
};

export const MAIL_INTERNAL_NOTES: Readonly<Record<string, readonly MailInternalNote[]>> = {
  [FIRST_ID]: [
    {
      author: 'Niraj Shah',
      ts: '2026-04-28 13:42',
      text: 'Marcus is the right contact here — billing@ alias forwards to him. Safe to send AI draft as‑is.',
    },
    { author: 'Kenji Tanaka', ts: '2026-04-28 14:05', text: 'Confirmed amendment §3.2 applies. Approve.' },
  ],
  [SECOND_ID]: [
    {
      author: 'Niraj Shah',
      ts: '2026-04-28 13:55',
      text: 'Banking change — route through verification protocol. Need callback to Greta on +1 312 555 0227 before clearing.',
    },
  ],
};

export const MAIL_SYNC: MailSyncStatus = {
  last_sync_seconds_ago: 8,
  next_poll_seconds: 52,
  graph_status: 'degraded',
  graph_note: 'throttling on /messages — 429s last 14m',
  sqs_visible: 3,
  sqs_in_flight: 1,
  sqs_dlq: 0,
};

export const MAIL_TEMPLATES: readonly MailTemplate[] = [
  { id: 'tpl_ack_received', name: 'Acknowledgment — received', category: 'Acknowledgment' },
  { id: 'tpl_w9_request', name: 'W‑9 request', category: 'Tax' },
  { id: 'tpl_short_pay_explain', name: 'Short‑pay explanation', category: 'Billing' },
  { id: 'tpl_banking_verify', name: 'Banking change — verification', category: 'Compliance' },
  { id: 'tpl_resolution_close', name: 'Resolution & closure', category: 'Closure' },
];

// Format a UTC ISO into a list-friendly time:
//  - same day → HH:MM (UTC)
//  - same year → "Apr 22"
//  - else → "Apr 22, 2025"
export function fmtMailTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date('2026-04-28T14:23:00Z');
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return d.toUTCString().slice(17, 22);
  const sameYear = d.getUTCFullYear() === now.getUTCFullYear();
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}

export function fmtBytes(b: number): string {
  return b > 1_000_000
    ? `${(b / 1_000_000).toFixed(1)} MB`
    : `${Math.round(b / 1000)} KB`;
}
