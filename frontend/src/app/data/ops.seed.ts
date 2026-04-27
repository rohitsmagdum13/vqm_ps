import type { QueryStatusReport, SystemSnapshot } from '../shared/models/ops';

export const SYSTEM_SNAPSHOT: SystemSnapshot = {
  timestamp_ist: '2026-04-25T07:35:00+05:30',
  dlq: [
    { queue_name: 'vqms-email-intake-dlq', depth: 0 },
    { queue_name: 'vqms-query-intake-dlq', depth: 0 },
    { queue_name: 'vqms-analysis-dlq', depth: 2 },
    { queue_name: 'vqms-routing-dlq', depth: 0 },
    { queue_name: 'vqms-communication-dlq', depth: 0 },
    { queue_name: 'vqms-dlq', depth: 1 },
  ],
  sla: {
    window_label: 'last 24h',
    total: 87,
    breached: 3,
    warning: 5,
    on_track: 79,
    breaches_by_path: { A: 1, B: 2, C: 0 },
  },
  queries_today: { received: 142, resolved: 124, in_progress: 18 },
  cost: {
    today_usd: 18.42,
    yesterday_usd: 22.10,
    avg_per_query_usd: 0.131,
    breakdown: { analysis: 8.20, resolution: 7.85, acknowledgment: 1.95, embeddings: 0.42 },
  },
  path_distribution_today: { A: 89, B: 32, C: 21 },
  pipeline_health: [
    { name: 'Bedrock', status: 'healthy', latency_p99_ms: 3200 },
    { name: 'PostgreSQL', status: 'healthy', latency_p99_ms: 12 },
    {
      name: 'Salesforce',
      status: 'degraded',
      latency_p99_ms: 4800,
      note: 'p99 latency above 4s threshold for 8m. Cache hit rate 94% so impact contained.',
    },
    { name: 'ServiceNow', status: 'healthy', latency_p99_ms: 850 },
    { name: 'Microsoft Graph', status: 'healthy', latency_p99_ms: 1100 },
    { name: 'EventBridge', status: 'healthy', latency_p99_ms: 45 },
    { name: 'SQS', status: 'healthy', latency_p99_ms: 18 },
  ],
  stuck_queries: [
    {
      query_id: 'VQ-2026-0123',
      vendor: 'TechNova Solutions',
      stuck_at_node: 'context_loading',
      stuck_for_min: 12,
    },
  ],
};

export const QUERY_STATUS_FIXTURES: ReadonlyArray<QueryStatusReport> = [
  {
    query_id: 'VQ-2026-0123',
    status: 'PAUSED_AWAITING_REVIEW',
    current_node: 'context_loading',
    path: 'C',
    opened_at: '2026-04-25T09:14:00+05:30',
    last_action_at: '2026-04-25T09:23:30+05:30',
    last_action: 'TriagePackage created (low confidence 0.62), workflow paused via callback token',
    correlation_id: 'b4e9c2a1-7f8d-4f3e-ae6c-7c4d3a8b2e91',
  },
  {
    query_id: 'VQ-2026-0089',
    status: 'RESOLVED',
    current_node: 'completed',
    path: 'A',
    opened_at: '2026-04-10T11:02:00+05:30',
    last_action_at: '2026-04-10T11:13:18+05:30',
    last_action: 'Resolution email sent via Graph API, ticket INC-7723451 closed',
    correlation_id: '3a7c1f2e-4d5b-9c8a-12fe-8b9d2a1c3e44',
  },
  {
    query_id: 'VQ-2026-0148',
    status: 'IN_PROGRESS',
    current_node: 'team_investigating',
    path: 'B',
    opened_at: '2026-04-24T14:30:00+05:30',
    last_action_at: '2026-04-25T05:45:12+05:30',
    last_action: 'Logistics team posted resolution note on INC-7725018; awaiting RESOLVED webhook',
    correlation_id: '8d2f9a1b-3c4e-7e6f-a5b9-2c1d4e7f3a82',
  },
];
