import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/** What the login form collects to connect an AWS account. */
export interface AwsCredentialsInput {
  region: string;
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken?: string;
  roleArn?: string;
  externalId?: string;
}

/** What the backend returns once the AWS identity is validated. */
export interface AuthResult {
  authSessionId: string;
  identityArn: string;
  region: string;
}

const STORAGE_KEY = 'cloudops.auth.session';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  private readonly _session = signal<AuthResult | null>(this.restore());
  readonly session = this._session.asReadonly();
  readonly authenticated = computed(() => this._session() !== null);

  /** Sent as `x-auth-session` on protected requests. */
  get authSessionId(): string | null {
    return this._session()?.authSessionId ?? null;
  }

  login(creds: AwsCredentialsInput): Observable<AuthResult> {
    return this.http
      .post<AuthResult>('/api/auth', creds)
      .pipe(tap((res) => this.setSession(res)));
  }

  logout(): void {
    const id = this.authSessionId;
    this.setSession(null);
    if (id) {
      this.http
        .post('/api/logout', {}, { headers: { 'x-auth-session': id } })
        .subscribe({ error: () => {} });
    }
  }

  private setSession(res: AuthResult | null): void {
    this._session.set(res);
    try {
      if (res) {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(res));
      } else {
        sessionStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // storage unavailable (private mode) — in-memory signal still works
    }
  }

  /**
   * Rehydrate the session id from sessionStorage so a refresh keeps you signed
   * in. If the server restarted, the id is stale — the first /api/chat 401s and
   * the widget sends you back to the login screen.
   */
  private restore(): AuthResult | null {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? (JSON.parse(raw) as AuthResult) : null;
    } catch {
      return null;
    }
  }
}
