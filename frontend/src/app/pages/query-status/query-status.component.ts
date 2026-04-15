import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { QueryService, QueryDetail, queryTypeLabel } from '../../services/query.service';

@Component({
  selector: 'app-query-status',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './query-status.component.html',
})
export class QueryStatusComponent implements OnInit {
  query: QueryDetail | null = null;
  error = '';
  queryTypeLabel = queryTypeLabel;

  constructor(
    private route: ActivatedRoute,
    private queryService: QueryService,
    private router: Router
  ) {}

  ngOnInit(): void {
    const queryId = this.route.snapshot.paramMap.get('id');
    if (!queryId) {
      this.error = 'No query ID provided';
      return;
    }

    this.queryService.getQueryById(queryId).subscribe({
      next: (data) => (this.query = data),
      error: (err) => {
        this.error = err.error?.detail || 'Failed to load query details';
      },
    });
  }

  back(): void {
    this.router.navigate(['/portal']);
  }
}
