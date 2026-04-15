import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { WizardService } from '../../services/wizard.service';

@Component({
  selector: 'app-new-query-details',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './new-query-details.component.html',
})
export class NewQueryDetailsComponent {
  subject = '';
  description = '';
  priority = 'MEDIUM';
  referenceNumber = '';

  priorities = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

  constructor(private wizard: WizardService, private router: Router) {
    // Restore previous values if user navigated back
    this.subject = this.wizard.subject || '';
    this.description = this.wizard.description || '';
    this.priority = this.wizard.priority || 'MEDIUM';
    this.referenceNumber = this.wizard.referenceNumber || '';
  }

  next(): void {
    if (!this.subject || !this.description) return;
    this.wizard.setDetails(this.subject, this.description, this.priority, this.referenceNumber);
    this.router.navigate(['/new-query-review']);
  }

  back(): void {
    // Save current state before going back
    this.wizard.setDetails(this.subject, this.description, this.priority, this.referenceNumber);
    this.router.navigate(['/new-query-type']);
  }
}
