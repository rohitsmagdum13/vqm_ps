export type Role = 'vendor' | 'admin';

export type BackendRole = 'ADMIN' | 'VENDOR' | 'REVIEWER';

export interface User {
  readonly name: string;
  readonly ini: string;
  readonly company: string;
  readonly role: string;
  readonly email: string;
}

export type UserMap = Readonly<Record<Role, User>>;

export interface AuthSession {
  readonly token: string;
  readonly userName: string;
  readonly email: string;
  readonly role: BackendRole;
  readonly tenant: string;
  readonly vendorId: string | null;
}

export function mapBackendRole(role: BackendRole): Role | null {
  if (role === 'ADMIN') return 'admin';
  if (role === 'VENDOR') return 'vendor';
  return null;
}
