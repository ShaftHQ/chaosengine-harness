# Installer URL cap measurement

Issue #129. Read-only GET with `curl -4`. Redirects were not followed. Nothing was submitted.

- Anonymous client: `curl -4, redirects not followed`
- Control status (short URL): `302`
- Lowest failing length: `6973` (HTTP `500`)
- First sampled HTTP 414: `8192`
- 80% of that boundary: `5578`
- Chosen cap: `5578` (lowered to 80% of the lowest boundary (6973))
- Product `MAX_ISSUE_URL_CHARS` left at `7800` in this slice (no product code change). #134 applies the chosen cap.
- Encoded/raw ratio for payloads that still fit: `1.2567` to `1.6758`
- A 50 KB trace is truncated by the current encoder before packing, so its packed ratio is not an expansion ratio. See `results.json`.
- Signed-in browser: not measured (no signed-in browser session in this environment)

Statuses are in `results.json`.
