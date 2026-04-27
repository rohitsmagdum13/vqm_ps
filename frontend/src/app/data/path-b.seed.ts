import type { PathBTicket } from '../shared/models/path-b';

export const SEED_PATH_B_TICKETS: readonly PathBTicket[] = [
  {
    ticket_id: 'INC-7725012',
    query_id: 'VQ-2026-0145',
    subject: 'Unexpected charge on invoice INV-8821 — needs investigation',
    body:
      'We received invoice INV-8821 dated April 18 with a line item "Q1 service adjustment $4,200" '
      + 'that was not on the original PO-2299. Could you confirm what this charge is for? '
      + 'Our finance team needs the breakdown before we can process payment.',
    vendor: {
      vendor_id: 'VEND-001',
      company_name: 'TechNova Solutions',
      tier: 'Gold',
      primary_contact: 'rajesh.kumar@technova.com',
      account_manager: 'Priya Sharma',
      annual_spend_usd: 1_250_000,
      industry: 'IT Services',
    },
    status: 'OPEN',
    priority: 'HIGH',
    team: 'AP-FINANCE',
    category: 'invoicing',
    ai_intent: 'invoice_dispute',
    opened_at: '2026-04-25T07:14:00+05:30',
    sla_target_hours: 8,
    sla_elapsed_hours: 1.5,
    acknowledgment_sent_at: '2026-04-25T07:15:30+05:30',
    acknowledgment_excerpt:
      'Hi Rajesh, we have received your invoice query (INV-8821) and opened ticket INC-7725012. '
      + 'Our AP team will investigate the line item discrepancy and respond within 8 business hours.',
    related_invoices: ['INV-8821'],
    related_pos: ['PO-2299'],
    resolution_notes: '',
  },
  {
    ticket_id: 'INC-7725018',
    query_id: 'VQ-2026-0148',
    subject: 'Shipment delayed — root cause needed',
    body:
      'Our shipment scheduled for April 22 has not arrived. Tracking shows it has been '
      + 'stuck at the Mumbai distribution hub since April 23. We need an updated ETA and '
      + 'an explanation for the delay before our production line is impacted.',
    vendor: {
      vendor_id: 'VEND-002',
      company_name: 'Delta Foods',
      tier: 'Silver',
      primary_contact: 'supplychain@deltafoods.com',
      account_manager: 'Anil Verma',
      annual_spend_usd: 480_000,
      industry: 'Food & Beverage',
    },
    status: 'IN_PROGRESS',
    priority: 'CRITICAL',
    team: 'LOGISTICS',
    category: 'logistics',
    ai_intent: 'delivery_delay',
    opened_at: '2026-04-24T14:30:00+05:30',
    sla_target_hours: 4,
    sla_elapsed_hours: 3.2,
    acknowledgment_sent_at: '2026-04-24T14:31:50+05:30',
    acknowledgment_excerpt:
      'Hello Delta Foods team, we have logged your delivery delay query as INC-7725018. '
      + 'Our logistics team is coordinating with the Mumbai hub and will respond within 4 business hours.',
    related_invoices: [],
    related_pos: ['PO-3107'],
    resolution_notes: 'Carrier confirmed truck breakdown. Replacement dispatched April 25 06:00. New ETA April 26 noon.',
  },
  {
    ticket_id: 'INC-7725022',
    query_id: 'VQ-2026-0151',
    subject: 'Contract renewal — clause 12.4 clarification',
    body:
      'Our contract is up for renewal in 30 days. We have questions about clause 12.4 '
      + 'regarding price escalation. Specifically, does the 5% cap apply per year or '
      + 'cumulatively across the renewal term?',
    vendor: {
      vendor_id: 'VEND-001',
      company_name: 'TechNova Solutions',
      tier: 'Gold',
      primary_contact: 'rajesh.kumar@technova.com',
      account_manager: 'Priya Sharma',
      annual_spend_usd: 1_250_000,
      industry: 'IT Services',
    },
    status: 'PENDING_VENDOR',
    priority: 'MEDIUM',
    team: 'PROCUREMENT',
    category: 'contract',
    ai_intent: 'contract_query',
    opened_at: '2026-04-23T10:15:00+05:30',
    sla_target_hours: 24,
    sla_elapsed_hours: 22.0,
    acknowledgment_sent_at: '2026-04-23T10:16:20+05:30',
    acknowledgment_excerpt:
      'Hi Rajesh, ticket INC-7725022 created for your contract clause query. '
      + 'Our procurement team will review clause 12.4 and respond within 24 business hours.',
    related_invoices: [],
    related_pos: [],
    resolution_notes:
      'Reviewed clause 12.4 with legal. Cap is 5% per year, NOT cumulative. Awaiting written confirmation from vendor on whether to proceed with renewal.',
  },
  {
    ticket_id: 'INC-7724567',
    query_id: 'VQ-2026-0118',
    subject: 'Compliance — ISO 27001 renewal documentation',
    body:
      'Our ISO 27001 certificate is expiring May 30. We need the documentation '
      + 'package required for renewal and the audit timeline.',
    vendor: {
      vendor_id: 'VEND-003',
      company_name: 'Acme Corp',
      tier: 'Bronze',
      primary_contact: 'billing@acmecorp.com',
      account_manager: 'Suresh Patel',
      annual_spend_usd: 95_000,
      industry: 'Manufacturing',
    },
    status: 'RESOLVED',
    priority: 'LOW',
    team: 'COMPLIANCE',
    category: 'compliance',
    ai_intent: 'compliance_query',
    opened_at: '2026-04-22T11:20:00+05:30',
    sla_target_hours: 48,
    sla_elapsed_hours: 36.0,
    acknowledgment_sent_at: '2026-04-22T11:21:40+05:30',
    acknowledgment_excerpt:
      'Hello Acme team, ticket INC-7724567 created for your ISO 27001 renewal query. '
      + 'Our compliance team will provide the renewal package within 48 business hours.',
    related_invoices: [],
    related_pos: [],
    resolution_notes:
      'Provided renewal package: (1) auditor contact list, (2) document checklist, (3) timeline (audit kickoff May 10, certificate issuance by May 25). Vendor confirmed receipt and audit booking.',
  },
];
