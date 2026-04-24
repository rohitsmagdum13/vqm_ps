export const environment = {
  production: false,
  // Matches the dev-mode backend start command in README.md:
  //   uv run uvicorn main:app --reload --port 8002
  // If you change the uvicorn --port, update this value to match or
  // the login call silently hits the wrong port and the UI stalls
  // on the login page with a "Cannot reach the server" toast.
  apiBaseUrl: 'http://localhost:8002',
} as const;
