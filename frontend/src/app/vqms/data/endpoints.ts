// Per-screen catalogs of backend endpoints the UI calls (or proposes calling).
// Surfaced via the "Endpoints" header button + drawer on every admin screen so
// developers can see the contract behind each view without leaving the app.

export type HttpVerb = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
export type EndpointStatus = 'exists' | 'new';

export interface EndpointSpec {
  readonly method: HttpVerb;
  readonly path: string;
  readonly status: EndpointStatus;
  readonly source: string;
  readonly note: string;
}

export const ENDPOINTS_OVERVIEW: readonly EndpointSpec[] = [
  {
    method: 'GET',
    path: '/admin/overview',
    status: 'exists',
    source: 'admin_overview.py',
    note:
      'bundled response: KPIs + 30d sparklines + path-mix + 30d volume + 24h hourly + ' +
      'confidence histogram + per-team SLA + top intents (single round-trip)',
  },
  {
    method: 'GET',
    path: '/admin/queries',
    status: 'exists',
    source: 'admin_queries.py',
    note: 'recent queries table — already wired via QueriesStore',
  },
  {
    method: 'GET',
    path: '/vendors',
    status: 'exists',
    source: 'vendors.py',
    note: 'vendor health side panel — already wired via VendorsStore',
  },
];

export const ENDPOINTS_INBOX: readonly EndpointSpec[] = [
  { method: 'GET', path: '/queries', status: 'exists', source: 'queries.py', note: 'list with filters: status, vendor_id, path, sla, priority, q' },
  { method: 'GET', path: '/queries/stats', status: 'exists', source: 'queries.py', note: 'counts by status / path / SLA bucket' },
  { method: 'GET', path: '/queries/{query_id}', status: 'exists', source: 'queries.py', note: 'single query + thread + audit' },
  { method: 'POST', path: '/queries/{query_id}/assign', status: 'exists', source: 'queries.py', note: '{ assignee_id }' },
  { method: 'POST', path: '/queries/{query_id}/reopen', status: 'exists', source: 'queries.py', note: 'moves CLOSED → IN_PROGRESS' },
  { method: 'POST', path: '/queries/{query_id}/comment', status: 'exists', source: 'queries.py', note: 'internal note, never sent to vendor' },
  { method: 'POST', path: '/queries/bulk', status: 'new', source: 'wraps assign/close', note: '{ ids[], action: assign|close|tag|reopen }' },
  { method: 'GET', path: '/queries/saved-views', status: 'new', source: 'workflow.saved_views', note: 'per-user inbox filter presets' },
  { method: 'POST', path: '/queries/saved-views', status: 'new', source: 'workflow.saved_views', note: 'persist current filter set' },
  { method: 'GET', path: '/queries/export.csv', status: 'new', source: 'queries.py', note: 'stream filtered list as CSV (S3-presigned)' },
];

export const ENDPOINTS_TRIAGE: readonly EndpointSpec[] = [
  { method: 'GET', path: '/triage/packages', status: 'exists', source: 'triage.py', note: 'Path C items needing human review, ordered by SLA' },
  { method: 'GET', path: '/triage/packages/{query_id}', status: 'exists', source: 'triage.py', note: 'full triage package: extract + KB + history + suggested action' },
  { method: 'POST', path: '/triage/packages/{query_id}/decision', status: 'exists', source: 'triage.py', note: '{ decision: APPROVE|REJECT|ESCALATE, reason, draft_id? }' },
  { method: 'POST', path: '/triage/packages/{query_id}/route', status: 'exists', source: 'triage.py', note: 'override path A/B/C assignment' },
  { method: 'POST', path: '/triage/packages/{query_id}/escalate', status: 'exists', source: 'ticketing.py', note: 'creates ServiceNow incident, links sys_id' },
  { method: 'POST', path: '/triage/packages/bulk-claim', status: 'new', source: 'extends triage.py', note: '{ ids[] } — atomic claim by current reviewer' },
  { method: 'GET', path: '/triage/leaderboard', status: 'new', source: 'workflow.audit_events', note: 'per-reviewer throughput + accuracy' },
  { method: 'POST', path: '/triage/packages/{query_id}/regenerate', status: 'new', source: 'wraps Bedrock invoke', note: 'force AI re-draft with reviewer hints' },
];

export const ENDPOINTS_VENDORS: readonly EndpointSpec[] = [
  { method: 'GET', path: '/vendors', status: 'exists', source: 'vendors.py', note: 'from Salesforce Vendor_Account__c (5min cache)' },
  { method: 'GET', path: '/vendors/{vendor_id}', status: 'exists', source: 'vendors.py', note: 'single vendor + open queries + health score' },
  { method: 'GET', path: '/vendors/{vendor_id}/queries', status: 'exists', source: 'queries.py', note: 'scoped to vendor' },
  { method: 'GET', path: '/vendors/{vendor_id}/timeline', status: 'exists', source: 'vendors.py', note: 'merged inbound + outbound + status events' },
  { method: 'GET', path: '/vendors/{vendor_id}/contacts', status: 'exists', source: 'vendors.py', note: 'Salesforce Vendor_Contact__c' },
  { method: 'GET', path: '/vendors/{vendor_id}/memory', status: 'exists', source: 'memory.py', note: 'episodic memory write-backs (Bedrock)' },
  { method: 'POST', path: '/vendors/{vendor_id}/health-recompute', status: 'new', source: 'vendors.py + sqs', note: 'force health-score recompute job' },
  { method: 'POST', path: '/vendors/{vendor_id}/notes', status: 'new', source: 'workflow.vendor_notes', note: 'internal-only notes pinned on Vendor 360' },
  { method: 'GET', path: '/vendors/export.csv', status: 'new', source: 'vendors.py', note: 'stream all vendors + counts' },
];

export const ENDPOINTS_VENDOR360: readonly EndpointSpec[] = [
  { method: 'GET', path: '/vendors/{vendor_id}', status: 'exists', source: 'vendors.py', note: 'header card + tier + region' },
  { method: 'GET', path: '/vendors/{vendor_id}/queries?status=open', status: 'exists', source: 'queries.py', note: 'open queries panel' },
  { method: 'GET', path: '/vendors/{vendor_id}/timeline', status: 'exists', source: 'vendors.py', note: 'activity feed' },
  { method: 'GET', path: '/vendors/{vendor_id}/contacts', status: 'exists', source: 'vendors.py', note: 'Vendor_Contact__c' },
  { method: 'GET', path: '/vendors/{vendor_id}/memory', status: 'exists', source: 'memory.py', note: 'Bedrock episodic memory entries' },
  { method: 'GET', path: '/vendors/{vendor_id}/sla-summary', status: 'new', source: 'wraps queries + audit', note: 'rolling 30/60/90-day SLA performance' },
  { method: 'POST', path: '/vendors/{vendor_id}/notes', status: 'new', source: 'workflow.vendor_notes', note: 'pin internal notes on the 360 view' },
];

export const ENDPOINTS_EMAIL_MONITOR: readonly EndpointSpec[] = [
  { method: 'GET', path: '/health', status: 'exists', source: 'health.py', note: 'Microsoft Graph + Amazon SQS depth + DLQ' },
  { method: 'GET', path: '/emails', status: 'exists', source: 'dashboard.py', note: 'ingestion log feed' },
  { method: 'GET', path: '/emails/stats', status: 'exists', source: 'dashboard.py', note: 'filtered/relevant/Path A-B-C counts' },
  { method: 'POST', path: '/admin/email/replay/{message_id}', status: 'exists', source: 'admin.py', note: 're-run a single message through the pipeline' },
  { method: 'POST', path: '/admin/email/replay-dlq', status: 'new', source: 'wraps admin.py', note: 'drain Amazon SQS DLQ in batches' },
  { method: 'GET', path: '/pipeline/throughput', status: 'new', source: 'Amazon CloudWatch', note: 'messages/min by stage, last 24h' },
  { method: 'GET', path: '/pipeline/textract-jobs', status: 'new', source: 'wraps Textract', note: 'in-flight + recent OCR jobs with confidence' },
];

export const ENDPOINTS_KB: readonly EndpointSpec[] = [
  { method: 'GET', path: '/kb/articles', status: 'exists', source: 'kb.py', note: 'list with vector + metadata filters' },
  { method: 'GET', path: '/kb/articles/{article_id}', status: 'exists', source: 'kb.py', note: 'single article + embedding info' },
  { method: 'POST', path: '/kb/search', status: 'exists', source: 'kb.py', note: '{ query, k } — Bedrock embedding + cosine over Postgres pgvector' },
  { method: 'POST', path: '/kb/articles', status: 'new', source: 'kb.py', note: '{ title, body_md, tags[] } — re-embeds on save' },
  { method: 'PATCH', path: '/kb/articles/{article_id}', status: 'new', source: 'kb.py', note: 'edit + bump version + re-embed' },
  { method: 'POST', path: '/kb/reindex', status: 'new', source: 'wraps Bedrock embed', note: 'force full re-embed (admin only)' },
];

export const ENDPOINTS_BULK: readonly EndpointSpec[] = [
  { method: 'POST', path: '/queries/bulk', status: 'new', source: 'wraps queries.py', note: '{ ids[], action } — assign / close / tag / reopen' },
  { method: 'POST', path: '/admin/email/bulk', status: 'new', source: 'wraps admin.py', note: '{ ids[], action: archive|reroute|replay }' },
  { method: 'POST', path: '/exports', status: 'new', source: 'exports.py', note: 'kicks off async CSV/XLSX export → S3' },
  { method: 'GET', path: '/exports/{export_id}', status: 'new', source: 'exports.py', note: 'poll job status + presigned URL' },
];

export const ENDPOINTS_AUDIT: readonly EndpointSpec[] = [
  { method: 'GET', path: '/audit', status: 'exists', source: 'audit.py', note: 'filterable: actor, target_type, action, time range' },
  { method: 'GET', path: '/audit/{event_id}', status: 'exists', source: 'audit.py', note: 'single event + before/after diff' },
  { method: 'GET', path: '/audit/export.csv', status: 'new', source: 'audit.py', note: 'stream filtered audit log' },
  { method: 'GET', path: '/audit/anomalies', status: 'new', source: 'wraps Bedrock', note: 'AI-flagged unusual actor/action pairs' },
];

export const ENDPOINTS_ADMIN: readonly EndpointSpec[] = [
  { method: 'GET', path: '/admin/users', status: 'exists', source: 'admin.py', note: 'user list + roles' },
  { method: 'POST', path: '/admin/users', status: 'exists', source: 'admin.py', note: 'invite by email' },
  { method: 'PATCH', path: '/admin/users/{user_id}', status: 'exists', source: 'admin.py', note: 'role / status changes' },
  { method: 'GET', path: '/admin/feature-flags', status: 'exists', source: 'admin.py', note: 'system feature toggles' },
  { method: 'PATCH', path: '/admin/feature-flags/{flag}', status: 'exists', source: 'admin.py', note: '{ enabled }' },
  { method: 'GET', path: '/admin/integrations', status: 'new', source: 'admin.py', note: 'connection state for Salesforce, Microsoft Graph, ServiceNow, Bedrock' },
  { method: 'POST', path: '/admin/integrations/{key}/test', status: 'new', source: 'admin.py', note: 'round-trip ping for selected integration' },
  { method: 'GET', path: '/admin/secrets', status: 'new', source: 'AWS Secrets Manager', note: 'metadata only — never plaintext values' },
];

export const ENDPOINTS_PORTAL: readonly EndpointSpec[] = [
  { method: 'POST', path: '/portal/auth/login', status: 'exists', source: 'auth.py', note: 'vendor JWT, scoped to single vendor_id' },
  { method: 'GET', path: '/portal/me', status: 'exists', source: 'portal.py', note: 'vendor profile + contact + tier' },
  { method: 'GET', path: '/portal/queries', status: 'exists', source: 'portal.py', note: 'queries WHERE vendor_id = me — never cross-vendor' },
  { method: 'GET', path: '/portal/queries/{query_id}', status: 'exists', source: 'portal.py', note: 'single query — RLS enforced' },
  { method: 'POST', path: '/portal/queries', status: 'exists', source: 'portal.py', note: '{ intent, subject, body, attachments[] } — uploads to S3 via presigned PUT' },
  { method: 'POST', path: '/portal/queries/{query_id}/reply', status: 'exists', source: 'portal.py', note: 'vendor adds message to thread; emits inbound EventBridge event' },
  { method: 'POST', path: '/portal/uploads/presign', status: 'exists', source: 'portal.py', note: 'returns S3 presigned PUT for attachments' },
  { method: 'GET', path: '/portal/notifications', status: 'new', source: 'portal.py', note: 'in-app notifications (status changes, replies)' },
  { method: 'POST', path: '/portal/notifications/{id}/ack', status: 'new', source: 'portal.py', note: 'mark notification read' },
  { method: 'GET', path: '/portal/sla/{query_id}', status: 'new', source: 'wraps queries.py', note: 'vendor-safe SLA view (no internal reviewer notes)' },
];

export const ENDPOINTS_MAIL: readonly EndpointSpec[] = [
  { method: 'GET', path: '/admin/mail', status: 'exists', source: 'extends GET /emails (dashboard.py)', note: 'add ?folder=&direction=&flagged=' },
  { method: 'GET', path: '/admin/mail/stats', status: 'exists', source: 'GET /emails/stats', note: 'folder counts' },
  { method: 'GET', path: '/admin/mail/{message_id}', status: 'new', source: '—', note: 'single message + thread + AI draft + audit' },
  { method: 'GET', path: '/admin/mail/thread/{conversation_id}', status: 'new', source: 'uses thread_correlator', note: 'full conversation by conversation_id' },
  { method: 'POST', path: '/admin/email/queries/{query_id}/reply', status: 'exists', source: 'admin_email.py', note: 'preserves conversationId, multipart for attachments' },
  { method: 'POST', path: '/admin/email/send', status: 'exists', source: 'admin_email.py', note: 'fresh compose, X-Request-Id idempotency' },
  { method: 'POST', path: '/admin/mail/{message_id}/forward', status: 'new', source: '—', note: 'wraps email_send.send_message' },
  { method: 'POST', path: '/admin/mail/{message_id}/link-query', status: 'new', source: '—', note: 'binds message → existing query_id' },
  { method: 'POST', path: '/admin/mail/{message_id}/create-query', status: 'new', source: 'wraps services/portal_submission', note: 'promotes orphan email to a query' },
  { method: 'POST', path: '/admin/mail/{message_id}/draft/approve', status: 'exists', source: 'admin_drafts.py', note: 'uses workflow.draft_responses approval' },
  { method: 'POST', path: '/admin/mail/{message_id}/draft/regenerate', status: 'new', source: '—', note: 're-runs resolution node' },
  { method: 'POST', path: '/admin/mail/{message_id}/draft/reject', status: 'exists', source: 'admin_drafts.py', note: 'rejection + reason' },
  { method: 'POST', path: '/admin/mail/{message_id}/notes', status: 'new', source: 'audit.action_log', note: 'internal note on message' },
  { method: 'POST', path: '/admin/mail/{message_id}/flag', status: 'new', source: '—', note: 'toggle flagged' },
  { method: 'POST', path: '/admin/mail/{message_id}/archive', status: 'new', source: '—', note: 'soft-archive' },
  { method: 'POST', path: '/admin/mail/bulk', status: 'new', source: '—', note: '{ids[], action: read|archive|assign|link_query}' },
  { method: 'GET', path: '/admin/mail/health', status: 'exists', source: 'GET /health', note: 'MS Graph + SQS sync status' },
  { method: 'GET', path: '/admin/mail/templates', status: 'new', source: 'S3 prefix templates/', note: 'list reply templates' },
];
