# Changelog

All notable changes to the `middlewarejson` project will be documented in this file.

## [1.2.0] - 2026-11-01

### Security Hardening & Resource Protection Release

#### Added
- **Non-Queuing Subscription Admission Guard (`MID-002`)**: Implemented `UpstreamRuntime` concurrency limiter with `max_inflight_subscriptions` (8). Rejects excessive upstream connection attempts with immediate HTTP 503 instead of unbounded connection queuing.
- **ASGI HeldResponse Streaming Wrapper**: Wraps streaming subscription responses to hold runtime admission leases until HTTP streaming completely finishes or disconnects, eliminating lease exhaustion under slow clients.
- **Recursive JSON Depth Guard (`MID-004`)**: Recursively inspects parsed JSON payloads with strict depth budget (`max_json_depth = 64`), preventing parser crashes and DoS stack overflows from malicious deeply nested upstream payloads.
- **Streaming & Decompression Budgets**: Enforces strict 2MiB decompressed body budget and total-I/O execution deadlines on upstream proxying.

#### Changed
- **SSRF & Catch-All Protection (`MID-001`, `MID-003`)**: Enforced strict URL scheme/host validation for upstream proxies and catch-all DNS targets.
- **Upstream Connection Pooling**: Reusable persistent HTTPX connection pools with cookie-jar isolation, preventing cross-client connection contamination.
- **Diagnostic Logging Sanitization**: Bearer tokens and sensitive query parameters automatically redacted from upstream proxy logs and BOM UTF-8 parsing normalized.

---

## [1.1.0] - 2026-11-01

### Pre-Audit Baseline Snapshot
- Baseline snapshot release capturing the state before security audit fixes (`2f089e0`).
- Happ technical subtitle preservation with blocked default outbound.
- Allowlist balancer and country flag configurations.
