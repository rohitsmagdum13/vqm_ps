import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { WizardService } from '../../services/wizard.service';
import { QueryService, SubmitResponse, queryTypeLabel } from '../../services/query.service';

@Component({
  selector: 'app-new-query-review',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './new-query-review.component.html',
})
export class NewQueryReviewComponent {
  error = '';
  submitted = false;
  result: SubmitResponse | null = null;
  queryTypeLabel = queryTypeLabel;

  constructor(
    public wizard: WizardService,
    private queryService: QueryService,
    private router: Router
  ) {}

  submit(): void {
    this.error = '';
    const payload = this.wizard.getSubmissionPayload();

    this.queryService.submitQuery(payload).subscribe({
      next: (res) => {
        this.submitted = true;
        this.result = res;
        this.wizard.clear();
      },
      error: (err) => {
        if (err.status === 409) {
          this.error = 'Duplicate query — you already submitted this exact query.';
        } else {
          this.error = err.error?.detail || 'Submission failed. Please try again.';
        }
      },
    });
  }

  back(): void {
    this.router.navigate(['/new-query-details']);
  }

  goToPortal(): void {
    this.router.navigate(['/portal']);
  }
}
