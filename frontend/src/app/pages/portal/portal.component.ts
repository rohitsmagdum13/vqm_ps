import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { QueryService, QueryItem, KpiResponse, queryTypeLabel } from '../../services/query.service';

@Component({
  selector: 'app-portal',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './portal.component.html',
})
export class PortalComponent implements OnInit {
  email = '';
  vendorId = '';
  kpis: KpiResponse = { open_queries: 0, resolved_queries: 0, avg_resolution_hours: 0, total_queries: 0 };
  queries: QueryItem[] = [];
  error = '';

  constructor(
    private auth: AuthService,
    private queryService: QueryService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.email = this.auth.getEmail() || '';
    this.vendorId = this.auth.getVendorId() || '';
    this.loadData();
  }

  loadData(): void {
    this.queryService.getKpis().subscribe({
      next: (data) => (this.kpis = data),
      error: () => (this.error = 'Failed to load KPIs'),
    });

    this.queryService.getQueries().subscribe({
      next: (data) => (this.queries = data.queries),
      error: () => (this.error = 'Failed to load queries'),
    });
  }

  queryTypeLabel = queryTypeLabel;

  newQuery(): void {
    this.router.navigate(['/new-query-type']);
  }
}
