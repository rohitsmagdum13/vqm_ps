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

  // Official VQMS query types — must match backend QUERY_TYPES in models/query.py
  queryTypes: { value: string; label: string }[] = [
    { value: 'RETURN_REFUND', label: 'Return & Refund' },
    { value: 'GENERAL_INQUIRY', label: 'General Inquiry' },
    { value: 'CATALOG_PRICING', label: 'Catalog & Pricing' },
    { value: 'CONTRACT_QUERY', label: 'Contract Query' },
    { value: 'PURCHASE_ORDER', label: 'Purchase Order' },
    { value: 'SLA_BREACH_REPORT', label: 'SLA Breach Report' },
    { value: 'DELIVERY_SHIPMENT', label: 'Delivery & Shipment' },
    { value: 'INVOICE_PAYMENT', label: 'Invoice & Payment' },
    { value: 'COMPLIANCE_AUDIT', label: 'Compliance & Audit' },
    { value: 'TECHNICAL_SUPPORT', label: 'Technical Support' },
    { value: 'ONBOARDING', label: 'Onboarding' },
    { value: 'QUALITY_ISSUE', label: 'Quality Issue' },
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
