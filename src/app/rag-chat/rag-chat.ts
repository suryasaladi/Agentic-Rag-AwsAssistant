import { Component, ElementRef, effect, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../auth/auth.service';
import { Citation, RagChatService } from './rag-chat.service';

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  citations?: Citation[];
  error?: boolean;
}

@Component({
  selector: 'app-rag-chat',
  imports: [FormsModule],
  templateUrl: './rag-chat.html',
  styleUrl: './rag-chat.scss'
})
export class RagChatComponent {
  private readonly rag = inject(RagChatService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly session = this.auth.session;
  protected readonly messages = signal<ChatMessage[]>([]);
  protected readonly draft = signal('');
  protected readonly loading = signal(false);

  private sessionId: string | null = null;

  private readonly scrollAnchor = viewChild<ElementRef<HTMLDivElement>>('scrollAnchor');

  constructor() {
    effect(() => {
      this.messages();
      this.loading();
      queueMicrotask(() =>
        this.scrollAnchor()?.nativeElement.scrollIntoView({ behavior: 'smooth' })
      );
    });
  }

  send(): void {
    const question = this.draft().trim();
    if (!question || this.loading()) {
      return;
    }

    this.messages.update((m) => [...m, { role: 'user', text: question }]);
    this.draft.set('');
    this.loading.set(true);

    this.rag.ask(question, this.sessionId).subscribe({
      next: (res) => {
        this.sessionId = res.sessionId ?? this.sessionId;
        this.messages.update((m) => [
          ...m,
          { role: 'assistant', text: res.answer, citations: res.citations ?? [] }
        ]);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        if (err?.status === 401) {
          this.logout();
          return;
        }
        const detail = err?.error?.error ?? err?.message ?? 'Request failed';
        this.messages.update((m) => [
          ...m,
          { role: 'assistant', text: `Something went wrong: ${detail}`, error: true }
        ]);
      }
    });
  }

  logout(): void {
    this.auth.logout();
    this.router.navigate(['/login']);
  }
}
