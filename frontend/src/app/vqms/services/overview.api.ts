import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

// Typed wrapper around GET /admin/overview. Types mirror
// src/models/admin_overview.py exactly. The single endpoint bundles
// every chart on the Overview screen so the frontend renders the page
// in one round-trip instead of eight.

export interface HeadlineKPIsDto {
  readonly queries_received: number;
  readonly queries_received_delta_pct: number;
  readonly resolution_rate_pct: number;
  readonly resolution_rate_delta_pct: number;
  readonly avg_response_minutes: number;
  readonly avg_response_delta_pct: number;
  readonly sla_breaches: number;
  readonly sla_breaches_delta_pct: number;
}

export interface KPISparklinesDto {
  readonly received_per_day: readonly number[];
  readonly resolution_rate_per_day: readonly number[];
  readonly response_minutes_per_day: readonly number[];
  readonly breaches_per_day: readonly number[];
}

export interface PathMixDto {
  readonly A: number;
  readonly B: number;
  readonly C: number;
}

export interface VolumeRowDto {
  readonly date: string;
  readonly A: number;
  readonly B: number;
  readonly C: number;
  readonly received: number;
}

export interface HourlyRowDto {
  readonly hour: string;
  readonly ingested: number;
  readonly resolved: number;
}

export interface ConfidenceBandDto {
  readonly band: string;
  readonly n: number;
}

export interface TeamSLADto {
  readonly team: string;
  readonly on_time: number;
  readonly breached: number;
}

export interface IntentBucketDto {
  readonly intent: string;
  readonly n: number;
}

export interface AdminOverviewDto {
  readonly kpis: HeadlineKPIsDto;
  readonly kpi_sparklines: KPISparklinesDto;
  readonly path_mix: PathMixDto;
  readonly volume_by_path: readonly VolumeRowDto[];
  readonly hourly_throughput: readonly HourlyRowDto[];
  readonly confidence_histogram: readonly ConfidenceBandDto[];
  readonly sla_by_team: readonly TeamSLADto[];
  readonly top_intents: readonly IntentBucketDto[];
}

@Injectable({ providedIn: 'root' })
export class OverviewApi {
  readonly #http = inject(HttpClient);
  readonly #baseUrl = environment.apiBaseUrl;

  get(): Observable<AdminOverviewDto> {
    return this.#http.get<AdminOverviewDto>(`${this.#baseUrl}/admin/overview`);
  }
}
