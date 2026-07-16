import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService, AwsCredentialsInput } from './auth.service';

@Component({
  selector: 'app-login',
  imports: [FormsModule, RouterLink],
  templateUrl: './login.html',
  styleUrl: './login.scss'
})
export class LoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly model = {
    region: 'us-east-1',
    accessKeyId: '',
    secretAccessKey: ''
  };

  submit(): void {
    if (this.loading()) {
      return;
    }
    this.error.set(null);
    this.loading.set(true);

    const payload: AwsCredentialsInput = {
      region: this.model.region.trim(),
      accessKeyId: this.model.accessKeyId.trim(),
      secretAccessKey: this.model.secretAccessKey.trim()
    };

    this.auth.login(payload).subscribe({
      next: () => {
        this.loading.set(false);
        this.router.navigate(['/']);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(err?.error?.error ?? err?.message ?? 'Could not connect to AWS.');
      }
    });
  }
}
