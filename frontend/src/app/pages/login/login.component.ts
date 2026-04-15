import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './login.component.html',
})
export class LoginComponent {
  usernameOrEmail = '';
  password = '';
  error = '';

  constructor(private auth: AuthService, private router: Router) {}

  login(): void {
    this.error = '';
    this.auth.login(this.usernameOrEmail, this.password).subscribe({
      next: () => {
        this.router.navigate(['/portal']);
      },
      error: (err) => {
        this.error = err.error?.detail || 'Login failed. Check credentials.';
      },
    });
  }
}
