import type { QueryType } from '../shared/models/qtype';

export const QTYPES: readonly QueryType[] = [
  { id: 'contract', ico: '📋', lbl: 'Contract Dispute', sub: 'Amendment, clause, penalty' },
  { id: 'invoice', ico: '💳', lbl: 'Invoice Issue', sub: 'Billing, payment, PO mismatch' },
  { id: 'delivery', ico: '🚚', lbl: 'Delivery Delay', sub: 'Shipment, ETA, logistics' },
  { id: 'tech', ico: '🔧', lbl: 'Tech Support', sub: 'Integration, API, system' },
  { id: 'sla', ico: '⏱️', lbl: 'SLA Clarification', sub: 'Policy, terms, breach' },
  { id: 'other', ico: '💬', lbl: 'Other', sub: 'General enquiry' },
];

export function qtypeById(id: string): QueryType | undefined {
  return QTYPES.find((t) => t.id === id);
}
