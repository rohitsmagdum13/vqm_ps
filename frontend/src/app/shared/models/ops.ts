export type ServiceStatus = 'healthy' | 'degraded' | 'down';

export interface ServiceHealth {
  readonly name: string;
  readonly status: ServiceStatus;
  readonly latency_p99_ms: number;
  readonly note?: string;
}

export interface DlqEntry {
  readonly queue_name: string;
  readonly depth: number;
}

export interface SlaSnapshot {
  readonly window_label: string;
  readonly total: number;
  readonly breached: number;
  readonly warning: number;
  readonly on_track: number;
  readonly breaches_by_path: { readonly A: number; readonly B: number; readonly C: number };
}

export interface CostSnapshot {
  readonly today_usd: number;
  readonly yesterday_usd: number;
  readonly avg_per_query_usd: number;
  readonly breakdown: {
    readonly analysis: number;
    readonly resolution: number;
    readonly acknowledgment: number;
    readonly embeddings: number;
  };
}

export interface PathDistribution {
  readonly A: number;
  readonly B: number;
  readonly C: number;
}

export interface StuckQuery {
  readonly query_id: string;
  readonly vendor: string;
  readonly stuck_at_node: string;
  readonly stuck_for_min: number;
}

export interface QueryStatusReport {
  readonly query_id: string;
  readonly status: string;
  readonly current_node: string;
  readonly path: 'A' | 'B' | 'C' | 'undetermined';
  readonly opened_at: string;
  readonly last_action_at: string;
  readonly last_action: string;
  readonly correlation_id: string;
}

export interface SystemSnapshot {
  readonly timestamp_ist: string;
  readonly dlq: readonly DlqEntry[];
  readonly sla: SlaSnapshot;
  readonly queries_today: { readonly received: number; readonly resolved: number; readonly in_progress: number };
  readonly cost: CostSnapshot;
  readonly path_distribution_today: PathDistribution;
  readonly pipeline_health: readonly ServiceHealth[];
  readonly stuck_queries: readonly StuckQuery[];
}
