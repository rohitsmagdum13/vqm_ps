import type { QueryType } from '../shared/models/qtype';
import type { BackendQueryType } from './query.service';

export const QTYPES: readonly QueryType[] = [
  { id: 'CONTRACT_QUERY', ico: '📋', lbl: 'Contract Query', sub: 'Amendment, clause, penalty' },
  { id: 'INVOICE_PAYMENT', ico: '💳', lbl: 'Invoice & Payment', sub: 'Billing, payment, PO mismatch' },
  { id: 'DELIVERY_SHIPMENT', ico: '🚚', lbl: 'Delivery & Shipment', sub: 'Shipment, ETA, logistics' },
  { id: 'TECHNICAL_SUPPORT', ico: '🔧', lbl: 'Tech Support', sub: 'Integration, API, system' },
  { id: 'SLA_BREACH_REPORT', ico: '⏱️', lbl: 'SLA Breach', sub: 'Policy, terms, breach' },
  { id: 'PURCHASE_ORDER', ico: '📦', lbl: 'Purchase Order', sub: 'PO creation, changes, cancel' },
  { id: 'RETURN_REFUND', ico: '↩️', lbl: 'Return & Refund', sub: 'Return approval, refund status' },
  { id: 'CATALOG_PRICING', ico: '🏷️', lbl: 'Catalog & Pricing', sub: 'Quotes, price list, SKU' },
  { id: 'COMPLIANCE_AUDIT', ico: '🛡️', lbl: 'Compliance & Audit', sub: 'Documents, certifications' },
  { id: 'ONBOARDING', ico: '🚀', lbl: 'Onboarding', sub: 'Account setup, access' },
  { id: 'QUALITY_ISSUE', ico: '🔬', lbl: 'Quality Issue', sub: 'Defects, product quality' },
  { id: 'GENERAL_INQUIRY', ico: '💬', lbl: 'General Inquiry', sub: 'Anything else' },
];

export function qtypeById(id: string): QueryType | undefined {
  return QTYPES.find((t) => t.id === id);
}

export function toBackendQueryType(id: string): BackendQueryType {
  const match = QTYPES.find((t) => t.id === id);
  return (match?.id as BackendQueryType) ?? 'GENERAL_INQUIRY';
}
