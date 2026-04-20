export const MAIL_STATUSES = ['New', 'Reopened', 'Resolved'] as const;
export type MailStatus = (typeof MAIL_STATUSES)[number];

export const MAIL_PRIORITIES = ['High', 'Medium', 'Low'] as const;
export type MailPriority = (typeof MAIL_PRIORITIES)[number];

export const MAIL_SORT_FIELDS = ['timestamp', 'status', 'priority'] as const;
export type MailSortField = (typeof MAIL_SORT_FIELDS)[number];

export type MailSortOrder = 'asc' | 'desc';

export const MAIL_THREAD_STATUSES = ['NEW', 'EXISTING_OPEN', 'REPLY_TO_CLOSED'] as const;
export type MailThreadStatus = (typeof MAIL_THREAD_STATUSES)[number];

export interface MailSender {
  readonly name: string;
  readonly email: string;
}

export interface MailAttachment {
  readonly attachment_id: string;
  readonly filename: string;
  readonly content_type: string;
  readonly size_bytes: number;
  readonly file_format: string;
}

export interface MailItem {
  readonly query_id: string;
  readonly sender: MailSender;
  readonly subject: string;
  readonly body: string;
  readonly timestamp: string;
  readonly attachments: readonly MailAttachment[];
  readonly thread_status: MailThreadStatus;
}

export interface MailChain {
  readonly conversation_id: string | null;
  readonly mail_items: readonly MailItem[];
  readonly status: MailStatus;
  readonly priority: MailPriority;
}

export interface MailChainList {
  readonly total: number;
  readonly page: number;
  readonly page_size: number;
  readonly mail_chains: readonly MailChain[];
}

export interface MailStats {
  readonly total_emails: number;
  readonly new_count: number;
  readonly reopened_count: number;
  readonly resolved_count: number;
  readonly priority_breakdown: Readonly<Record<MailPriority, number>>;
  readonly today_count: number;
  readonly this_week_count: number;
}

export interface MailAttachmentDownload {
  readonly attachment_id: string;
  readonly filename: string;
  readonly download_url: string;
  readonly expires_in_seconds: number;
}

export interface MailListQuery {
  readonly page?: number;
  readonly page_size?: number;
  readonly status?: MailStatus;
  readonly priority?: MailPriority;
  readonly search?: string;
  readonly sort_by?: MailSortField;
  readonly sort_order?: MailSortOrder;
}
