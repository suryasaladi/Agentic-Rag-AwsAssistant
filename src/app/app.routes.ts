import { Routes } from '@angular/router';
import { authGuard } from './auth/auth-guard';
import { LoginComponent } from './auth/login';
import { RagChatComponent } from './rag-chat/rag-chat';

export const routes: Routes = [
  { path: 'login', component: LoginComponent },
  { path: '', component: RagChatComponent, canActivate: [authGuard] },
  { path: '**', redirectTo: '' }
];
