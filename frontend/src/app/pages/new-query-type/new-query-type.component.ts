import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { WizardService } from '../../services/wizard.service';

@Component({
  selector: 'app-new-query-type',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './new-query-type.component.html',
})
export class NewQueryTypeComponent {
  selectedType = '';

  queryTypes = [
    'Invoice Query',
    'Payment Status',
    'Contract Question',
    'General Inquiry',
    'Compliance Question',
    'Technical Support',
  ];

  constructor(private wizard: WizardService, private router: Router) {
    // Restore previous selection if user navigated back
    this.selectedType = this.wizard.queryType || '';
  }

  next(): void {
    if (!this.selectedType) return;
    this.wizard.setQueryType(this.selectedType);
    this.router.navigate(['/new-query-details']);
  }

  back(): void {
    this.router.navigate(['/portal']);
  }
}
