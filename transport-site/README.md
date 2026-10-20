# Riff Studio Transport

Private Sites-hosted MCP Apps transport for the existing Riff ChatGPT plugin.
Native inference, library, scores, LoRAs and drafts remain in the user ChatGPT Chat cloud runtime. This service stores only expiring pairing/heartbeat records and transient command/results in R2.

`worker/relay.js` is the source. `worker/index.js` is derived by the downstream repo script `scripts/build_relay.py` from this source, the existing 18 adapter tool schemas and the complete original studio. The build does not rewrite the original studio to a lookalike. See `contract-receipt.json`.

Run `node --test tests/relay.test.js`, `bash scripts/build.sh` and `node scripts/validate-artifact.mjs`. Publish using the Sites source workflow with the existing project ID. Keep it private during acceptance.

A cloud worker claims a one-use, five-minute enrollment token created by the authenticated user MCP connection, receives its own one-hour worker capability, and polls only that paired session. Commands are claimed using R2 etag compare-and-swap. Claimed commands are never delivered again. A local SQLite journal prevents native mutation replay after process loss. Completed results are erased after delivery; disconnect deletes queued transport messages. Expired sessions are inaccessible immediately and their messages are collected in bounded background scans.

Sites service-access credentials are used only for private owner acceptance, outside the package. They must never be shipped as a shared developer credential. Before general availability, the transport needs an internet-accessible runtime route with its existing per-session authorization, while MCP calls retain Sites-authenticated per-user identity. The private Site audience must not be changed silently.
