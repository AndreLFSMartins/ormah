# Local admin API authentication

Sensitive desktop-only routes require an installation-local capability in the
`X-Ormah-Local-Token` header and reject non-loopback peers. The server creates the capability at
`~/.local/share/ormah/local_api_token` with mode `0600`. It is independent of the Ormah Cloud
account token.

The desktop integration must keep this boundary native: Tauri reads the owner-only capability and
adds the header to requests it makes to the local Python server. React asks a narrow Tauri command
to perform the request; React never receives either the local capability or
`ORMAH_ACCOUNT_TOKEN`. Browser-only callers cannot use these billing routes.

`POST /admin/account/portal` requires an explicit empty JSON object (`{}`). The body carries no
customer or redirect input; requiring JSON ensures browser requests are preflighted before the
owner-only capability is checked.
