import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AuthService } from '../auth/auth.service';

/** A single supporting passage the backend retrieved from the knowledge base. */
export interface Citation {
  text: string;
  source: string | null;
  uri: string | null;
}

/** Shape the backend `/api/chat` endpoint returns. */
export interface ChatResponse {
  answer: string;
  citations: Citation[];
  sessionId: string | null;
}

@Injectable({ providedIn: 'root' })
export class RagChatService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  private readonly endpoint = '/api/chat';

  /**
   * Ask the Cloud Ops agent a question. The AWS auth session is sent via the
   * `x-auth-session` header so the backend runs tools as that identity.
   */
  ask(question: string, sessionId: string | null): Observable<ChatResponse> {
    const headers = new HttpHeaders({ 'x-auth-session': this.auth.authSessionId ?? '' });
    return this.http.post<ChatResponse>(this.endpoint, { question, sessionId }, { headers });
  }
}
