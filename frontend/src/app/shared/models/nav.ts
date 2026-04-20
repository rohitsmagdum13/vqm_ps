export interface NavItem {
  readonly id: string;
  readonly route: string;
  readonly lbl: string;
  readonly ico: string;
  readonly badge: string | null;
  readonly exact?: boolean;
}
