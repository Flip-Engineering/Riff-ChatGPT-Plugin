# Riff ChatGPT plugin: protocol and acceptance

This document records the wire contracts used by `plugins/riff-chatgpt`, the
automated checks that exercise them, and the evidence still needed from a real
ChatGPT host. Protocol review date: **2026-10-19**.

The implementation wraps Riff's original studio and native runtime. The MCP App
is the visual interface; the MCP server owns the private native backend. A local
plugin package does not by itself provide native execution to ChatGPT web or
mobile. Successful unit tests, packaging, or a private plugin listing do not
establish that a host launched the runtime or rendered a YuE2 take.

## Sources and protocol generations

The server protocol and the app-to-host protocol have different version numbers.
Do not replace one with the other.

| Interface | Contract | Primary reference |
| --- | --- | --- |
| Host to Riff server | MCP `2026-07-28`, per-request metadata; legacy `initialize` compatibility | [MCP schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.ts), [versioning](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/versioning.mdx) |
| Local server transport | One UTF-8 JSON-RPC message per line on stdio | [stdio transport](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/stdio.mdx) |
| Studio iframe to host | MCP Apps `2026-01-26` | [MCP Apps wire types](https://github.com/modelcontextprotocol/ext-apps/blob/main/src/spec.types.ts), [SDK initialization and methods](https://github.com/modelcontextprotocol/ext-apps/blob/main/src/app.ts) |
| ChatGPT navigation, settings and context | OpenAI MCP Extensions, negotiated per feature | [Extensions specification](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md), [integration patterns](https://github.com/openai/mcp-extensions/blob/main/docs/patterns.md) |
| Resource errors | Modern missing-resource error is `-32602`; earlier hosts may use `-32002` | [Resource error handling](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/resources.mdx#error-handling) |

The reviewed Git blob SHA for the MCP schema was
`9b55feeb412bc3ae877f2eac10b5c01ba29a2eed`; for the MCP Apps wire types,
`0c45396378b0e4ae5911563ec048e95906a04c1e`; for the OpenAI Extensions
specification, `2ec09948a58c341f132569f0a76d7f9003888f7c`. These are source
identifiers, not server protocol versions. The protocol tests assert the documented
wire behavior rather than importing a changing remote schema at test time.

## Server discovery and request handling

Modern MCP has no initialization handshake. Every request supplies its version
and current client capabilities in `params._meta`. Discovery is useful but is
not a prerequisite for listing tools, reading the UI, or calling a tool.

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientCapabilities": {}
    }
  }
}
```

The server checks these fields on each modern request. It must not infer a new
request's optional capabilities from an earlier request. Unsupported versions
receive error `-32022` with `data.supported` and `data.requested`, so the client
can select a mutually supported version. An explicitly supplied protocol
version must be a nonempty string; malformed version or capabilities metadata
is an invalid-parameters error. These requirements come from the
[versioning contract](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/versioning.mdx).

Riff makes one intentional compatibility concession: a metadata-free,
read-only `server/discover` request can return its discovery declaration.
This does not establish client capabilities or authorize later requests.
Other operations require complete modern request metadata or an established
legacy initialization. This concession is implementation behavior, not a
claim that such a discovery request conforms to the modern request schema.

`server/discover` returns supported versions, tools/resources capabilities, the
OpenAI settings capability, and server identity in
`_meta["io.modelcontextprotocol/serverInfo"]`. A modern successful result has
`resultType: "complete"`. Discovery, tool/resource listings, and resource reads
also include `ttlMs` and `cacheScope`, as required by `CacheableResult`. Static
declarations may use public cache scope; user-specific data must not be placed
in a publicly reusable cached result. See the [canonical discovery example](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/examples/DiscoverResult/server-capabilities-discovery.json).

Legacy clients can use `initialize` with the older supported revision and then
send their ordinary requests. A modern request remains independently validated
even when the same process has received a legacy initialization. The
implementation does not advertise resource subscriptions or change
notifications it cannot deliver.

| Condition | Wire behavior |
| --- | --- |
| Invalid JSON, including non-finite JSON constants | `-32700`; continue at the next bounded frame |
| Invalid JSON-RPC envelope or request ID | `-32600` |
| Unknown method | `-32601` |
| Unknown tool, malformed method parameters, or missing modern resource | `-32602` |
| Unsupported modern version | `-32022`, with supported/requested version data |
| Expected tool execution failure, such as unavailable engine | Tool result with `isError: true` and an actionable text explanation |
| Unexpected internal exception | Sanitized error on the protocol channel; details only in the private diagnostic log |
| Notification without a request ID | No response; do not execute an id-less mutation request |
| Input frame exceeds the configured limit | Emit one error and close the stream without interpreting its remainder |

The parser must preserve numeric ID `0` and string IDs. Boolean values are not
MCP request IDs. All stdout output is protocol JSON; startup progress, native
logs, and diagnostics go to stderr. [MCP stdio](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/stdio.mdx)
defines the framing and logging separation.

## Visual entrypoints and resources

Riff uses separate titled tools for the global studio and thread view:

| Tool | Title | Entrypoint | Required arguments |
| --- | --- | --- | --- |
| `riff_open_studio` | Riff | `global` | None; accepts `{}` |
| `riff_open_project` | Current song | `thread` | None; accepts `{}` |

Each tool has one entrypoint in `_meta["openai/ui"].entrypoints` and a
`_meta.ui.resourceUri` pointing to a listed `ui://` resource. The resource read
returns a complete bundled HTML document with
`mimeType: "text/html;profile=mcp-app"`. Its content-item metadata specifies
`preferredDisplayMode: "fullscreen"` and its available display modes.
ChatGPT supports `inline` and `fullscreen`; `pip` is not a ChatGPT mode. The
[Extensions specification](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md#mcp-app-entrypoints)
and [entrypoint patterns](https://github.com/openai/mcp-extensions/blob/main/docs/patterns.md#declaration)
define this registration.

The bundled HTML carries the original studio's controls and assets. Its API
transport goes through host-proxied tools; the iframe is not granted arbitrary
network access or a localhost origin. MCP resource metadata must declare any
actual external origin an app needs. The host may impose further CSP
restrictions, so a local mock-host test is not evidence that blob workers,
media playback, or exports are accepted by the production host. [MCP Apps CSP](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/draft/apps.mdx#ui-resource-format)
defines these restrictions.

The app installs its message/result handlers before sending:

```json
{
  "jsonrpc": "2.0",
  "id": "riff-ui-init",
  "method": "ui/initialize",
  "params": {
    "appInfo": {"name": "Riff", "version": "1.0.0"},
    "appCapabilities": {"availableDisplayModes": ["inline", "fullscreen"]},
    "protocolVersion": "2026-01-26"
  }
}
```

It then sends `ui/notifications/initialized`. A raw `postMessage` transport is
supported by MCP Apps, although the SDK is also available. The bridge validates
the sending window and correlates response IDs without consuming unrelated
notifications. Tool-input arguments arrive in `params.arguments`; a
`ui/notifications/tool-result` notification carries the `CallToolResult`
directly as its `params`, including `_meta`. Host-context notifications contain
partial updates and must be merged. These shapes are defined by the
[current wire types](https://github.com/modelcontextprotocol/ext-apps/blob/main/src/spec.types.ts).

## Tools, media and state

Model-visible tools expose explicit Riff operations, including reading state,
editing the current recipe, and queueing a generation. The broad UI gateway and
binary-transfer tools use `_meta.ui.visibility: ["app"]`. This visibility is a
host presentation rule, not a substitute for validating every route, ID,
method, payload, and byte range in the server.

`riff_audio_chunk` retains the track-specific WAV contract.
`riff_media_chunk` uses an allowlisted media path and returns bounded bytes in
`result._meta["riff/media"]`, with its MIME type and suggested filename. Both
return `content: []`; their `structuredContent` describes only transfer
position, byte counts, total size, and completion. Binary bytes are not placed
in text or ordinary structured results. Conservatively treat `content` and
`structuredContent` as model-readable; reserve result `_meta` for UI-only
payloads. The [tool-result contract](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/draft/apps.mdx#data-passing)
distinguishes the result channels.

The native engine is the authority on generation readiness and queue status.
A queue acknowledgement does not mean an audio file exists. Missing models,
native execution failures, cancellation, and interrupted work must remain
visible rather than producing placeholder success data. Contract tests use an
explicit unavailable-engine backend double; they never manufacture a successful
YuE2 recording.

The packaged runtime fixes its native executable, backend and model locations.
The UI gateway does not grant the embedded app authority to replace them:
`POST /api/system/engine` accepts only thread count, device and warm-engine
preferences. If the original studio form includes executable or model fields,
the adapter compares them with the current trusted engine configuration,
rejects any change, and removes unchanged fields before forwarding the tuning
update. Unknown settings fields are rejected before mutation. This boundary
prevents an app tool call from selecting a host executable or model path.

The saved draft uses a monotonically increasing revision. A save supplies its
expected revision; simultaneous writers cannot silently replace one another's
work. Settings persist separately and do not change the draft revision.

### Native settings

The discovery capability is:

```json
{
  "openai/settings": {
    "readTool": "riff_settings_read",
    "updateTool": "riff_settings_update"
  }
}
```

For modern MCP this is under `capabilities.extensions`. Legacy connections can
advertise the documented experimental compatibility form.
`riff_settings_read` is read-only, accepts `{}`, and declares an `outputSchema`
for its direct `structuredContent: {schema, values, layout}`. It does not wrap
these fields in the HTTP gateway's `{status, body}` envelope. Each schema
property has a current or default value. Updates have `{set: {...}}` shape,
validate all supplied properties before persisting, and retain unspecified
values. The [native settings specification](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md#structured-settings)
defines this contract.

## Chat context, file export and lifecycle

`ui/update-model-context` supplies the active recipe, selected take and related
high-level state. A new update replaces the previous app context, so the bridge
must send its complete intended current state. Explicit attachments belong in
`content`; background state belongs in `structuredContent`. Respect host
capabilities and the user's context-sharing preference. Audio blocks are not
supported in OpenAI's app context/message extension; use a resource link and
textual recipe information. Work web also lacks image context support. See
[OpenAI model context](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md#uiupdate-model-context-extensions).

The host-mediated new-file export API is **`ui/download-file`**, guarded by
`hostCapabilities.downloadFile`. An embedded text or base64 binary resource
can be downloaded without granting the app a filesystem path:

```json
{
  "contents": [
    {
      "type": "resource",
      "resource": {
        "uri": "file:///take.wav",
        "mimeType": "audio/wav",
        "blob": "BASE64_OF_THE_REQUESTED_EXPORT"
      }
    }
  ]
}
```

Here the URI provides a suggested filename, not authority to write that path.
The host can decline a download or impose a size limit. Inspect both protocol
errors and a result with `isError: true`, and do not report a cancelled download
as saved. Normal iframe anchor downloads may be blocked because the sandbox
does not grant `allow-downloads`. The [download wire types](https://github.com/modelcontextprotocol/ext-apps/blob/main/src/spec.types.ts)
and [SDK `downloadFile`](https://github.com/modelcontextprotocol/ext-apps/blob/main/src/app.ts)
document the supported API.

This is distinct from `openai/resources/write`, which updates an already
opened, host-authorized writable resource. File extension handlers, local-file
resource access, and composer at-mentions are desktop-only in the current
OpenAI platform table. Ordinary in-app imports and exports remain necessary
for compatible web views. No file-handler declaration should imply universal
host filesystem access. [OpenAI platform support and file access](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md#platform-support)
specify these limits.

On `ui/resource-teardown`, the app handles a host request: save an intended
pending draft, stop polling, release media buffers/object URLs, and acknowledge
the request. Closing one studio view must not close the native server shared by
other views. The MCP process owns its runtime; its final stream shutdown is a
separate lifecycle event. A second process must not concurrently own the same
workspace. Persistent interrupted work is reopened through Riff's native
recovery behavior, not through a claim that the stopped process continued
rendering. See [MCP Apps teardown](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/draft/apps.mdx#4-teardown)
and [stdio lifecycle](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/stdio.mdx).

## Automated checks and live acceptance

Run the independent protocol suite from the repository root:

```sh
python3 -m unittest discover -s plugins/riff-chatgpt/tests -p test_protocol_contract.py -v
```

It uses the production `Adapter`, `RPC`, stream parser and SQLite stores, with
only the native HTTP backend replaced. It covers modern per-request operation,
legacy compatibility, discovery/cache fields, malformed frames, schema
rejections without side effects, entrypoint/resource linkage, native settings,
media privacy/range limits, draft conflicts and visible engine failures.

The independent run on 2026-10-19 passed all 26 protocol contract tests,
including native path binding and WebM preview transfer. This is protocol and
adapter evidence; it does not attest to an installed ChatGPT host or an actual
YuE2 inference run.

| Acceptance area | Evidence needed |
| --- | --- |
| Protocol and durable state | Passing protocol tests plus the adapter's integration tests |
| Bundled original studio | Build receipt, bridge tests, actual bundled HTML and source preservation checks |
| Native process ownership | Runtime tests for exclusive workspace ownership, clean shutdown and restart |
| Installation | The intended host actually launches the packaged command and discovers its tools |
| Visual integration | Global and thread views render inside that host, respond to tool results and restore state |
| Playback and files | The host allows the declared media strategy; imports work; a requested export reaches the host download flow |
| Music inference | Real installed weights produce a completed take and playable audio on supported native hardware |

Only record a gate as passed when its corresponding evidence exists. A mock
host cannot establish production-host CSP behavior, and a valid plugin archive
cannot establish web/mobile native runtime support. A hosted edition would
add an authenticated remote native renderer; the current local package does
not provision one.
