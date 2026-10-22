# NextByDesign — Empathise research workspace

Supabase-backed Module 1 with named sign-in and project permissions.

Deploy this repository as a Docker Web Service on Render. The Dockerfile is at
repository root. No separate build or start command is needed.

Set these server environment variables in Render:
- SUPABASE_URL: https://rlnpziwjrforgsbxljwi.supabase.co
- SUPABASE_PUBLISHABLE_KEY: your public project key
- SUPABASE_SECRET_KEY: your private server secret, entered only in Render
- PUBLIC_ORIGIN: the deployed HTTPS address, without a trailing slash

The existing Supabase migration has already been applied for this project.
The application serves its frontend and API together. GitHub Pages cannot run it.
Do not upload .env, local-data, .venv, server keys, or research exports.
