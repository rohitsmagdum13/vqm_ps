// Convert backend `MailChainDto[]` (src/api/routes/dashboard.py) into the UI's
// flat `MailThread[]` shape used by the Mail screen. The dashboard groups
// emails by conversation_id; the UI renders one row per message in the list,
// so we flatten chains here while preserving conversation linkage.

import { VENDORS } from './mock-data';
import type {
  MailAttachment,
  MailDirection,
  MailStatus,
  MailThread,
} from './mail';
import type {
  AttachmentSummaryDto,
  MailChainDto,
  MailItemDto,
} from '../services/mail.api';
import type { ProcessingPath, TierName } from './models';

const SUPPORT_INBOX = 'vendor-support@hexaware.com';

function vendorName(vendorId: string | null): { name: string; tier: TierName } {
  if (!vendorId) return { name: '—', tier: 'SILVER' };
  const v = VENDORS.find((x) => x.vendor_id === vendorId);
  return { name: v?.name ?? '—', tier: (v?.tier as TierName) ?? 'SILVER' };
}

// Anything coming from the support mailbox is outbound; everything else is
// vendor → us. The dashboard endpoint doesn't expose direction, so we infer
// from the sender address.
function inferDirection(sender: string): MailDirection {
  return sender.toLowerCase() === SUPPORT_INBOX ? 'outbound' : 'inbound';
}

// Backend `status` is the chain-level rollup ("New" | "Reopened" | "Resolved").
// The UI's per-row status is more granular ("unread" | "read" | "sent" | "draft");
// we only have hints, so default to "read" once a chain has any activity and
// "unread" for fresh New chains.
function inferRowStatus(
  chainStatus: string,
  direction: MailDirection,
  isFirstInChain: boolean,
): MailStatus {
  if (direction === 'outbound') return 'sent';
  if (chainStatus === 'New' && isFirstInChain) return 'unread';
  return 'read';
}

function mapPath(value: string): ProcessingPath {
  if (value === 'A' || value === 'B' || value === 'C') return value;
  return 'C';
}

function mapAttachment(a: AttachmentSummaryDto): MailAttachment {
  return {
    attachment_id: a.attachment_id,
    filename: a.filename,
    size_bytes: a.size_bytes,
    mime_type: a.content_type,
    s3_key: a.download_url ?? '',
  };
}

function mapItem(item: MailItemDto, chain: MailChainDto, idx: number): MailThread {
  const direction = inferDirection(item.sender.email);
  const v = vendorName(item.vendor_id);
  // The dashboard payload doesn't carry processing_path or confidence
  // (those live on workflow.case_execution, not intake). Use safe defaults
  // until we extend the endpoint.
  const path: ProcessingPath = 'B';
  const confidence = 0.0;
  return {
    message_id: item.message_id,
    conversation_id: item.conversation_id ?? `solo_${item.message_id}`,
    in_reply_to: item.in_reply_to,
    from_address: item.sender.email,
    from_name: item.sender.name || item.sender.email,
    to_addresses: item.to_recipients.map((r) => r.email),
    cc_addresses: item.cc_recipients.map((r) => r.email),
    subject: item.subject,
    body_text: item.body,
    body_html: item.body_html,
    received_at: item.timestamp,
    ingestion_status: 'PROCESSED',
    processed_at: item.parsed_at,
    attachments: item.attachments.map(mapAttachment),
    query_id: item.query_id,
    processing_path: mapPath(path),
    confidence_score: confidence,
    assigned_team: null,
    ticket_id: null,
    vendor_id: item.vendor_id ?? '—',
    vendor_name: v.name,
    vendor_tier: v.tier,
    _direction: direction,
    _status: inferRowStatus(chain.status, direction, idx === 0),
    _flagged: false,
    _has_ai_draft: false,
    _sla_pct: null,
  };
}

/**
 * Flatten `MailChainDto[]` (backend grouping by conversation_id) into the
 * `MailThread[]` array the Mail screen consumes. Items are emitted in the
 * order the backend returned them — each chain is sorted newest-first by
 * the dashboard service.
 */
export function toMailThreads(chains: readonly MailChainDto[]): readonly MailThread[] {
  const out: MailThread[] = [];
  for (const chain of chains) {
    chain.mail_items.forEach((item, idx) => {
      out.push(mapItem(item, chain, idx));
    });
  }
  return out;
}
