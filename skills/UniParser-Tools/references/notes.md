# Important Notes

## Result Quality and Retention

- High-quality modes use generative models and may omit, misread, misassociate, or add plausible-looking content across text, tables, equations, charts, figures, reactions, and molecules. Verify critical fields, numbers, equations, names, and structures against the source. Do not use parsing output as the sole basis for high-risk decisions.
- High-quality table parsing recovers semantics and structure but does not provide precise source-page coordinates for each cell. Choose a method that explicitly provides position data when downstream work requires overlays, highlighting, or coordinate-level auditing.
- Chart parsing may recover labels, legends, axes, values, or trends incorrectly. Verify precise values and interpretations against the original chart.
- High-quality modes are slower. Prefer asynchronous submission with suitable polling, callbacks, and timeouts for long documents or batches.
- Online parsing results are retained for only **24 hours**. Fetch and store required results promptly; a task token is not a long-term storage reference.

## Key Points

1. **Concurrency Limit**: Maximum 5 concurrent requests on public service

2. **Token Reuse**: A token can be used multiple times to fetch different formats

3. **Host Selection**: Different hosts may have different features/quality
   - `https://uniparser.dp.tech/` - Official site

4. **Callback Verification**: Use HMAC-SHA256 with `callback_secret` to verify callbacks
   ```python
   import hmac
   import hashlib


   def verify_callback(raw_body: bytes, signature: str, secret: str) -> bool:
       if not signature.startswith("sha256="):
           return False
       expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
       return hmac.compare_digest(expected, signature[len("sha256=") :])
   ```
   Read `raw_body` before JSON parsing and take `signature` from the
   `X-UniParser-Signature` header. The body is not wrapped in
   `checksum` / `content` fields.

5. **Ordering Methods**: Default is `GapTree`; alternatives: `Naive`, `XYCut`, `XYCutExp`

6. **Page Selection**: Use `pages=[1, 2, 3]` to parse specific pages only
   ```python
   result = parser.trigger_file(
       file_path="./document.pdf",
       pages=[1, 2, 3],  # Only parse pages 1, 2, 3
   )
   ```

## Error Response Format

All API methods return a dict with consistent structure:

```python
# Success
{
    "status": "success",
    "token": "abc123...",
    ...
}

# Transport or trigger error with an unconfirmed deterministic token
{
    "status": "error",
    "candidate_token": "abc123...",
    "candidate_token_recoverable": False,
    "message": "Error description",
    "description": "Detailed traceback (optional)"
}
```

Only a successful trigger response contains a confirmed task `token`. SDK error responses can contain a
`candidate_token` when the caller uses the backward-compatible deterministic-token mode; do not poll or fetch it
unless a separate service status check confirms that the task exists. CLI and MCP default to server-generated tokens;
the CLI exposes `recoverable_token` only after confirmation, while MCP resumes a confirmed duplicate internally.

## Common Error Messages

CLI workflow errors (config, duplicate token, 502, etc.) are documented in SKILL.md **Common issues**. This table covers additional SDK/API messages when calling the client directly:

| Error | Cause | Solution |
|-------|-------|----------|
| `token: ... contains illegal characters` | Invalid token format | Token must match `^[-\._?=&a-zA-Z0-9]{1,128}$` |
| `host must start with http or https` | Invalid host URL | Use full URL including protocol |
