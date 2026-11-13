# Cataran Contract Conformance — Provisional Snapshot

This repository pins the common event envelope only from UGAI's proposed Platform Contracts v1.

- Upstream: StrategyG/Universal-Generative-AI PR #34 (open, not merged; proposal not released)
- Upstream commit: `a4b3311f752699db7c411989bcdc7025431d38fd`
- Schema Git blob SHA-1: `02e8dca953eed529abbfbde2873c2d7f5a705011`
- Fixture Git blob SHA-1: `4cbe6f8f6f090356e9bbae55e7800cbab82497fd`
- Validator: `jsonschema==4.26.0`

CI validates schema syntax, the golden fixture, invalid identifiers/versions, nested credential-like property-key rejection and trace context.

This snapshot does not prove full platform-contract conformance, runtime integration, tenant isolation or production readiness. Update only through a reviewed PR recording exact upstream commit and blob digests; never fetch a floating latest schema during CI.
