export const VENDOR_TIERS = ['PLATINUM', 'GOLD', 'SILVER', 'BRONZE'] as const;
export type VendorTier = (typeof VENDOR_TIERS)[number];

export const VENDOR_STATUSES = ['ACTIVE', 'INACTIVE'] as const;
export type VendorStatus = (typeof VENDOR_STATUSES)[number];

export interface Vendor {
  readonly id: string;
  readonly name: string;
  readonly vendor_id: string | null;
  readonly website: string | null;
  readonly vendor_tier: VendorTier | null;
  readonly category: string | null;
  readonly payment_terms: string | null;
  readonly annual_revenue: number | null;
  readonly sla_response_hours: number | null;
  readonly sla_resolution_days: number | null;
  readonly vendor_status: VendorStatus | null;
  readonly onboarded_date: string | null;
  readonly billing_city: string | null;
  readonly billing_state: string | null;
  readonly billing_country: string | null;
}

export interface VendorCreateInput {
  readonly name: string;
  readonly website?: string | null;
  readonly vendor_tier?: VendorTier | null;
  readonly category?: string | null;
  readonly payment_terms?: string | null;
  readonly annual_revenue?: number | null;
  readonly sla_response_hours?: number | null;
  readonly sla_resolution_days?: number | null;
  readonly vendor_status?: VendorStatus | null;
  readonly onboarded_date?: string | null;
  readonly billing_city?: string | null;
  readonly billing_state?: string | null;
  readonly billing_country?: string | null;
}

export type VendorUpdateInput = Partial<Omit<VendorCreateInput, 'name'>> & {
  readonly name?: string;
};

export interface VendorCreateResult {
  readonly success: boolean;
  readonly salesforce_id: string;
  readonly vendor_id: string;
  readonly name: string;
  readonly message: string;
  readonly vendor: Vendor | null;
}

export interface VendorUpdateResult {
  readonly success: boolean;
  readonly vendor_id: string;
  readonly updated_fields: readonly string[];
  readonly message: string;
  readonly vendor: Vendor | null;
}

export interface VendorDeleteResult {
  readonly success: boolean;
  readonly vendor_id: string;
  readonly message: string;
}
