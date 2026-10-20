# Riff in ChatGPT Chat

The cloud package runs Riff in each user's ChatGPT Chat cloud execution environment. It has
no external inference backend and never uses the developer's homelab or the user's
local computer as its production backend. The homelab remains a build/CI host.
Private installation and real native generation have passed in ChatGPT Chat.
The original 0.3.0 package required writable-path, socket and setup recoveries;
0.3.1 replaces its socket transports; 0.3.2 adds file-lock worker ownership and
the reusable recording player. Actual Chat verified that the host reaps detached
workers between execution calls: 0.3.2 restarts safely and preserves drafts, while
setup/render/polling must share a retained execution session. The connected full studio is privately installed as 0.4.1; measured host checks
and remaining limits are recorded below.

Version 0.3.3 was privately installed on the existing Riff plugin identity. Its
installed native export command and the actual Chat inline player display passed
acceptance. The renderer and audio controls also passed sandboxed Chromium tests;
direct playback inside Chat's own nested iframe now passes trusted-click, audio advancement, seeking, loop-wrap and changing original-canvas checks.

## OpenAI documentation contract

The implementation follows these documented distinctions:

- [Plugin architecture](https://developers.openai.com/plugins/concepts/plugins)
  supports skills containing instructions and supporting scripts, references,
  templates or assets. A skills-only plugin can use tools already available to
  the model; an MCP server is a separate integration.
- [Build skills](https://developers.openai.com/plugins/build/skills) permits
  deterministic helper scripts under `scripts/`. This is the basis for the
  cloud command adapter, rather than a bundled stdio MCP connection.
- [Package your plugin](https://developers.openai.com/plugins/build/plugins)
  defines root `plugin.json`, `skills/`, relative asset paths and
  `extensions.com.openai`. Installing a plugin on the web does not deploy
  lifecycle-hook scripts.
- [Desktop-only plugins](https://developers.openai.com/plugins/deploy/desktop-only)
  identifies local stdio MCP servers as a desktop execution path. A packaged
  local server must not be described as an automatically hosted cloud MCP service.
- [Add UI](https://developers.openai.com/plugins/build/chatgpt-ui) requires an
  MCP server to associate a tool with a UI resource, and an MCP Apps host bridge
  for component interaction. Including studio source in a skill archive does
  not register that studio as a ChatGPT UI component.
- [Connect and test](https://developers.openai.com/plugins/deploy/connect-chatgpt)
  requires testing the installed package in a new conversation with
  representative requests and verifying bundled-resource resolution.

These pages do not guarantee native Riff execution, a fixed cloud CPU/memory
allocation, background-worker persistence, or a route from a skills-only
command worker to an MCP App. Those remain explicit compatibility questions;
host probes are implementation evidence, not substitutes for platform documentation.

The documented [shared archive checks](https://developers.openai.com/plugins/deploy/submission-errors#archive-errors)
limit the ZIP to 100 MB compressed, 512 MiB extracted, 100 MiB per member and
5,000 entries. The native runtime is a compressed skill asset; validation must
check both the outer plugin archive and the extracted runtime independently.

The cloud distribution is a portable plugin containing a skill, a small Python
launcher and a checksum-verified native runtime archive. The candidate launcher currently requires Python 3.12+; Chat must supply it
or the launcher must be adapted after checking its actual runtime. The package carries the pinned Riff source, CPU YuE2 engine,
Elixir/ERTS score/control runtime, media executables, libraries, studio source
and component notices. The separately licensed music models download from the
pinned public Hugging Face revision into the user's cloud workspace.

A worker inside that cloud computer uses a private SQLite mailbox. Native
studio request handlers run in that same process without an HTTP listener.
Successive
cloud command calls use the existing adapter and share the same native jobs,
drafts, LoRA library and recordings. No network/Unix listener or developer credentials
are needed. The original stdio/MCP App distribution remains separate.
Worker liveness is established by a kernel-held file lock rather than PID lookup,
which is unreliable across execution namespaces and succeeds for zombies or
reused PIDs. Worker loss reports the request identity promptly. On restart,
unfinished mailbox requests are failed for inspection rather than replayed.

Build a complete Linux CPU platform package with the existing builder, then:

```sh
python3 scripts/package_cloud_plugin.py \
  --runtime-package /absolute/platform/package/riff-chatgpt \
  --output /absolute/output/riff-chatgpt-cloud.zip
```

Install the resulting archive through ChatGPT's private plugin importer and
start a fresh Chat conversation. The skill launches its bundled runtime with:

```sh
python3 /path/to/skill/scripts/riff.py start
python3 /path/to/skill/scripts/riff.py call riff_read --arguments '{"path":"/api/state"}'
```

`--arguments @/path/to/file.json` supports complete recipes without shell
interpolation. App-only binary metadata is omitted from stdout; use
`--output-file` to preserve a full transport result privately. Export original
recordings through the host's Library instead of embedding audio bytes in chat.

Cloud workspace persistence is bounded by the cloud computer's lifetime. Models
may need to download again after reset. Publish requested recordings and recipe
receipts to the user's Library. A queued job is not completed audio.

## Recording panel

The cloud skill now includes `scripts/player.py`. It reads a real recording and
its native visualization through the existing adapter, transfers WAV bytes using
the declared bounded audio chunks, and exports self-contained HTML. It carries
the pinned upstream `artwork.js` and `motionAt` unchanged,
and a receipt with audio/source hashes and measured WAV metadata. No audio bytes
enter model context. The skill asks Chat to display this exact file through the
host's HTML/Visualize capability and publish audio to Library.

```sh
python3 /path/to/skill/scripts/player.py --track-id RECORDING_ID \
  --output /writable/path/riff-player.html
```

This recording player supports playback, seek, loop and download. It does not
provide a live native command connection for library, LoRA or score controls.
Those remain available conversationally through the adapter. Full studio
navigation and editing require the registered MCP UI transport described above;
bundling the studio alone does not establish it.

The installed Visualize helper requires an **HTML fragment**, and documents and
enforces a **1,000,000-byte fragment limit**. The export omits document wrappers
so it can use the host's source-path registration/display workflow unchanged.
Version 0.3.3 preserves the exact embedded WAV when it fits;
larger recordings use a clearly labeled 128 kbit/s MP3 preview created with the
bundled FFmpeg. Preview duration follows from the remaining fragment capacity,
including actual encoder overhead. All original motion frames are gzip-compressed
without loss. The complete original WAV stays in Library. The panel can open
that downloaded WAV through a local file picker, verify its original SHA-256,
and play/visualize the complete recording without uploading it or making HTTP
requests. A preview is never described as a full original WAV.

The Visualize instructions do not document a large-media upload bridge; their
preview policy does not permit arbitrary HTTPS media or Library download URLs.
The connected MCP studio now transfers full recordings in bounded chunks, independently
of the standalone fragment limit. Remaining acceptance is tracked in [issue #2](https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin/issues/2).

On October 20, the actual Chat acceptance conversation generated recording
`cfeb4193acd84a87b12ce9800bd204f4`: 47,936 stereo PCM16 frames at 48 kHz,
0.998666667 seconds, native exit 0, seed 1234, two midpoint acoustic steps.
The original WAV SHA-256 is
`314375cb23ea17bd6c2762e637b649e42f878d6b3184bf6226def9acb8080523`.
Chat displayed an HTML recording player using the original Riff renderer and
actual motion data. The browser's conversation iframe was observed, but playback
inside that host iframe was not independently inspected. The reusable packaged
player passed a separate Chromium test of playback time, seeking, looping,
changing artwork, media identity and title-injection handling without HTTP.

The native studio returned HTTP 200 inside the Chat execution environment;
Chat's separate cloud browser received `ERR_CONNECTION_REFUSED` at its loopback
address. A direct studio response also forbids framing. An external UI transport
would have to connect the host panel to each user's cloud worker; the developer's
homelab is not a runtime backend.

## Installed 0.3.3 acceptance, October 20

The final cloud archive was packaged from `d14782e`, with SHA-256
`a50b791846ab728e1be3a171fda3e81e7a588c2a6254c9c80d96e36558188063`
and size 56,998,097 bytes. Browser-side byte count and SHA-256 matched before
upload. Chat confirmed the existing plugin had updated to 0.3.3.

A fresh Chat then reused native recording `a006eb3c51174f42bde14dcac379a4c8`
from the successful 0.3.2 render. It checked that no job was running, left an
unrelated process with a reused PID untouched, started the new package in a
retained session, and stopped it gracefully after export. No new render or draft
mutation was performed in this final export test.

| Check | Evidence |
| --- | --- |
| Real native generation | 0.3.2 completed one YuE2 job with native exit 0, 47,936 stereo PCM16 frames at 48 kHz, seed 1234 and two midpoint steps. Models passed their six pinned size/SHA checks. |
| Installed export command | 0.3.3 `scripts/player.py` exited 0 through native `riff_audio_chunk`; no direct builder-import workaround or runtime patch. |
| Exact audio | Original and embedded WAV were 191,788 bytes, SHA-256 `3b946eccd47220e3fcdecc84bd0e5ee2c58a63fb8de3a72f895b3a3db039c4f3`. |
| Host format | 306,139-byte fragment; installed Visualize `render.py` exited 0; no document wrappers. Original artwork and motion function were present verbatim, and decompressed motion data matched the native response. |
| Chat display | The final response mounted an iframe titled “Riff 033 Native Player”. |
| Browser controls | Two Chromium tests passed in an opaque sandbox iframe with an offline CSP: trusted keyboard playback, seek, loop, changing canvas frames, exact audio hashes, title injection, MP3 fragment budget, wrong-file rejection and full-WAV selection. No HTTP requests or relaxed autoplay policy. |
| Network-enabled download | The host's approved network-enabled `curl` fetched one 466-byte pinned sidecar, `yue2-generation-config.json`, SHA-256 `203830cebde6e3644eb291925362990d198e66c3b6006cd11f1aaa21904bcc61`. The restricted executor's native HTTPS download had failed; supported host execution can provide the pinned files. |

Source regression validation passed 96 Python tests, five packaging tests and 26
bridge tests. Linux archive acceptance exercised native runtime components and
the installed player CLI with an explicit PCM transport fixture; that smoke is
not a neural generation test. The real generation above occurred in Chat.

Subsequent inspection through the existing signed-in Chrome connection reached the
actual nested Chat iframe. A trusted native-player click advanced `currentTime`
from 0.521333 to 0.870651 seconds while the original canvas changed. Looping
crossed 0.982444 to zero and continued to 0.722662; seeking to 0.5 succeeded.
The player was paused and reset afterward. The full connected studio remains
tracked in issue #2. The short native render establishes functionality;
no listening or musical-quality acceptance is claimed.

## Historical Work probe: not Chat acceptance

On October 20, a fresh ChatGPT Work browser chat executed a read-only probe in
its cloud environment: Ubuntu 24.04.3, glibc 2.39, x86-64, the required AVX2/FMA/
BMI2/F16C flags, an 8 GiB cgroup memory limit, eight CPU equivalents and roughly
28 GiB available disk. Native ELF execution succeeded. GitHub and Hugging Face
responded to bounded HTTPS requests. Python 3.12.14, FFmpeg/FFprobe and Node
were present; CMake, Erlang and Elixir were not on PATH. The package carries its
score runtime and requires no compiler in the user's cloud computer.

This Work probe does not validate the required Chat surface.
These are measured compatibility results for one cloud environment, not a
promise that every future cloud computer is identical. Bundle validation checks
architecture, glibc, CPU requirements and every carried file before startup.

Cloud native generation, account installation and the browser UI must be
verified independently. The CLI does not mount an interactive MCP App. Preserve
the complete studio in the package and report actual cloud preview/MCP UI
support; do not label a returned resource reference as an opened studio.


## Private connected studio transport (0.4.3)

The existing native plugin keeps its identity. Its cloud package declares a dependency
on the separately provisioned, canonical Sites transport App
`asdk_app_sites_47b8744149508191b69a7fe838be8b6d`, verified in Chat settings.
The companion plugin is `plugin_asdk_app_sites_47b8744149508191b69a7fe838be8b6d`.
No second MCP server mapping is registered for the same Site.

The transport is privately deployed at
https://riff-studio-transport.amusedcorgi5.chatgpt.site. It is an MCP Apps bridge,
not an inference backend. It serves the full original studio (906,291 bytes in 0.4.3) and
all 18 original adapter tool schemas. User identity comes from Sites-authenticated
MCP requests. A one-use five-minute enrollment creates an isolated one-hour
worker capability for the user's own Chat runtime. The helper makes only outbound
HTTPS requests to that fixed origin; native handlers remain socket-free.

Transient commands/results pass through R2 with compare-and-swap claims and
bounded chunks; media remains in hidden tool metadata. The local SQLite journal
prevents mutation replay after an interrupted exchange. Results are erased after
delivery, disconnect erases session messages, and expired sessions are immediately
inaccessible and collected by bounded background scans. Native library, drafts,
LoRAs, scores and models remain in the cloud workspace.

Nine transport tests cover R2 rate-limit recovery, bounded retry, heartbeat throttling, FIFO scheduling, concurrent enrollment, cross-user isolation, native
command envelope/media preservation, one-time claims, offline handling and
authenticated commands. Seven Python relay tests cover late-result retention, response retry, crash recovery, duplicate mutations, rejection of
arbitrary endpoints, bounded transient-poll recovery and fatal authorization
rejection. The 103-test source suite, five packaging tests and 30 bridge tests pass. The
complete original-studio browser fixture also passes with production ManagedRiff
and stdio MCP; its neural generation step is explicitly a test double.

Private acceptance can pass a Sites owner service-access token through an
untracked, mode-600 file. It is never shipped in source, an archive, an enrollment
or a shared prompt. This private access path does not establish general-user
availability. The Site remains owner-private; making its runtime route generally
reachable requires an explicit audience decision and retains per-session runtime
authorization and authenticated MCP identity. Measured connected-studio host
acceptance follows.


### Installed full studio checks, October 20

The initial full-studio checks used the existing Riff plugin at version 0.4.1. That archive was built from
`e1269f6`, is 57,002,896 bytes, and has SHA-256
`50d5a105cad8cf5a3ec4da63052e0279da661a59c843e3c97c8a3afda751ba4a`.
The native executables are reused from the verified Linux CPU platform package;
the derived manifest includes the current downstream Python adapter and studio.
A Linux installation smoke passed startup, native state/draft reads, exact audio
transfer, installed player export and graceful shutdown using an explicit PCM
fixture. No new neural generation is claimed for that smoke.

The registered MCP App opens the original full studio in Chat, including Library,
LoRA browser/Installed controls and the composition workspace. The fresh cloud
filesystem lacked the earlier recording, so its authentic WAV and recipe/metrics
were imported using the original Store.add_track API into an isolated acceptance
workspace. Native reads list that recording and zero jobs. The actual studio
iframe fetched the complete 191,788-byte WAV; a browser-side SHA-256 matched
`3b946eccd47220e3fcdecc84bd0e5ee2c58a63fb8de3a72f895b3a3db039c4f3`.
A trusted playback click advanced 0.213954 to 0.529040 seconds, and the seek
control moved to 0.5 seconds. After the 0.4.1 runtime upgrade, another trusted click
advanced from zero to 0.144561 seconds while the original canvas SHA-256 changed
from `e61d3744b2382cf6ad96c49ba5ccba6564c81fc14b5df87ab74da9316d4b0065`
to `a243435f0abed69b7b0a75e568dcf0da4bf431e1d25c2b57a285d058a0768adf`.
The original studio's 0.4.2 Chat panel also passed looping: with a 0.2–0.8-second
region, playback repeatedly wrapped from approximately 0.66 to 0.2 seconds while
remaining unpaused. The previous standalone player passed independently.
The original studio successfully browsed Hugging Face, inspected the pinned
`becausereasons/yue2-trbdr-folk-troubadour` revision
`078b19e52baebaa71463ea94afac5ce13abfe29a`, and installed
`trbdr_broadside.safetensors`. The cloud workspace initially had no base models.
Using the panel’s **Download music models** completed the normal pinned setup:
2,933,414,997 verified bytes, engine ready, no missing files. Native LoRA support
then became enabled, and **Use this style** selected both composition and sound
adapters at strength 1. This proves catalog, inspection, installation, setup and
selection in the host; it does not prove LoRA-conditioned audio quality.

The original composition workspace created and rendered an ABC sketch. Editing
its melody and saving from the panel produced shared draft revision 1, independently
read back through Chat’s native tool. A compare-and-swap update changed only the
shared title at revision 2. The panel retained its unsaved title and complete ABC,
showing the expected conflict warning instead of overwriting browser edits.

The panel also transferred a complete 180-second stereo PCM16 WAV fixture:
34,560,044 bytes, SHA-256
`7fb20be0960503021bd484d221da0a34e95069727a27d614fa9ba2513498fdef`.
The browser verified the entire blob, sought to 120 seconds, and trusted playback
advanced from 120.129156 to 120.444453. The fixture repeats the authentic short
recording; it is explicitly labeled transport-only, not a newly generated song.
Transfer is sequential in 1 MiB chunks and took several minutes in this private
acceptance session.

Host failures repaired during acceptance:

- Resource scans received the complete HTML but did not register an asset until
  resource responses included the MCP cache fields. Refreshing tools then
  registered the template and mounted the actual iframe.
- The host media policy initially rejected local blob/data URLs. The versioned
  `ui://riff/studio/adapter-v0.2.1.html` resource permits exactly `blob:` and
  `data:` assets, with no external connection origins. Actual host media loading
  and exact-WAV playback passed after refreshing the registered resource.
- The queue originally followed random UUID ordering; FIFO deadline ordering
  prevents repeated state/draft polls from jumping ahead of older requests.
- An unhandled HTTP 400 from polling terminated the relay while the native
  worker remained alive. The old session was resumed without replaying requests.
  Version 0.4.1 retries transient polling failures up to three times and reports
  unexpected hosted storage faults as service failures with diagnostic logs.
  Authorization/session rejections remain fatal. The original poll error body
  was not retained, so its underlying storage/network cause is not established.


### File export compatibility (0.4.2–0.4.3)

The actual Chat MCP host did not advertise the shared `downloadFile` capability.
Its documented optional `window.openai.uploadFile` extension was present, but
rejected the real WAV with `Unsupported file type`. The bridge therefore keeps
shared MCP downloads when supported, feature-detects the documented Chat file
extension for other exports, and labels the recording action **WAV to Chat**
when direct app downloads are absent. The shared `ui/message` request did not
produce a persisted conversation message in actual Chat testing; an instrumented
second request remained pending. Version 0.4.3 prefers the documented
`window.openai.sendFollowUpMessage({prompt})` extension when present, choosing
one path before sending and never retrying through another API after an uncertain
send. This requests export of the original recording from the paired workspace to Library.
It reports **export requested**, not **export ready**, until Chat performs the
actual export. A different conversation with no access to that cloud workspace
must report the mismatch rather than imply the file was saved.

This is a host compatibility path, not a change to audio bytes or MIME types.
The UI does not rename a WAV to pretend it is a supported document, open a native
socket, or use the homelab as a file/inference backend. OpenAI's exact
[file API signatures](https://developers.openai.com/plugins/reference#file-apis)
and [shared UI methods](https://developers.openai.com/plugins/build/chatgpt-ui#prefer-shared-fields-and-methods)
are the implementation contract. Direct file-library export support varies by
host and file type; ABC/MIDI/MP4 export acceptance is separate from the passed
browser protocol fixture.

The final 0.4.2 archive was built from `dd95662`: 57,003,133 bytes, SHA-256
`fc51300db862ba0b7d75f3ab071a31bbd4d01927a9d5951f40903101ea940244`.
The existing plugin importer confirmed **New version uploaded**. Its Linux
installed-archive smoke passed startup, native state/draft reads, exact WAV
transfer, installed player export and graceful shutdown with a PCM fixture.
The private transport is Site version 8, source
`e44c9bbcba0870cccd72ad21666a75fdd937b74f`, deployment
`appgdep_6ad7bd48c654819183a9f6c5dc24e5bc`, resource
`ui://riff/studio/adapter-v0.2.3.html`. No audience change was made.

Version 0.4.3 was built from `6fc24816398cbf92424d5287b4d96c21c17d9882`:
57,003,474 bytes, SHA-256
`a1a2787294c44458ef0664a0e615b57127b7dc46bc3d4437b547b9c13a26935e`.
Its installed Linux smoke passed native startup, state/draft reads, exact WAV
transfer, player export and graceful stop with an explicit PCM fixture.
Site version 9 deployed successfully from
`a0e151f5a25e7affada10d6f78c5be8e54ba0f75`, deployment
`appgdep_6ad7c0b50528819186de28021e008e25`, resource
`ui://riff/studio/adapter-v0.2.4.html`. The full studio HTML SHA-256 is
`0171e13eea2784b8bbc28299edd4d795f5d2224e873739f3d1c39a50daa84ad7`.

This release also fixes a separate relay defect: HTTP 409 rejecting a late
command completion now retains that command's cached result and continues the
relay, without replaying its native operation. Other authorization/session
rejections remain fatal. The older relay session 83589 disappeared before its
pairing expired, but its retained log contains only the initial connected event
and no exit status or traceback. Its termination cause is unknown; the new
late-completion test does not establish the cause of that historical exit.

Actual 0.4.3 cloud upgrade checks confirmed the same workspace's ready models,
enabled LoRA, both preserved recordings and unchanged shared draft revision 2.
The refreshed full studio loaded the original WAV and its installed bridge
contains the follow-up extension. A single trusted physical **WAV to Chat** click
returned from `sendFollowUpMessage` and displayed the requested status, but Chat
remained on **Stop** for several minutes without a visible new response. That
stalled request was stopped and the page reloaded. This is **failed host export
acceptance**, not proof of publication. The original composition's **Export ABC**
and **Export MIDI** also returned `Unsupported file type` from `uploadFile`.
Normal conversation/file-output recovery and relay process lifetime are being
checked separately. See [host exports #4](https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin/issues/4)
and [relay lifetime #3](https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin/issues/3).

Recovery through a normal conversation confirmed the original short recording,
recipe and original recording receipt in Library. The saved WAV was independently
retrieved and matched all 191,788 original bytes and the SHA-256 above; the saved
recipe is 2,709 bytes and recording receipt 8,996 bytes. The earlier prepared
upload helper failed before writing with `hosted apps tools/list request failed
with HTTP status 403`; a separate documented Chat file-output route completed.
Its successful records were reconciled without submitting a duplicate save.
This proves conversation export, while the panel button's acceptance remains failed.

A controlled launch of the identical bundled relay with
`subprocess.Popen(start_new_session=True, stdin=DEVNULL)` and stdout/stderr to a
private mode-600 log survived its launcher returning. Separate execution calls
confirmed the same detached process alive 204 seconds later, reparented to PID 1;
real companion state/draft/LoRA requests returned HTTP 200. The original native
worker remained alive, both recording rows/recipes/metrics and shared draft
were unchanged, and all 789 existing journal rows were preserved. This is a
measured process-lifetime improvement, not proof of full pairing-lifetime survival
or the cause of earlier session losses. A later normal-turn check passed at
19:52:15–19:52:25 UTC: same relay and native-worker start identities, companion
online, shared draft still revision 2. The original player favorite control also
changed native metadata from false to true and back; independent native reads
confirmed both values and final restoration to false.

Version 0.4.4 packages that measured detached-launch recipe in the cloud skill,
including one-instance/ownership checks, private logs, post-launch native reads,
and retained-session fallback when a host reaps detached workers. It also records
the observed panel-export limitations and verified normal-conversation file-output
recovery. It does not change the native engine, original studio code or Site.
Archive source `57672390a1beb59859405f384fd88baa6b32cbde`, 57,004,465 bytes,
SHA-256 `934de83a1d468437d469c2368bebfb5dc7efd40cfb5b47fbdaed70416243054f`.
Five packaging tests and the final installed Linux smoke passed; the smoke used
an explicit PCM fixture, not new neural generation.

The actual 0.4.4 cloud upgrade passed at 20:05:15 UTC: one detached relay,
one native worker, ready models, enabled LoRA, both recordings, original favorite
value false and complete shared draft revision 2 preserved. All 28 model/LoRA
files (7,248,447,133 bytes) were rehashed with no mismatch; all nine installed
manifest pins still matched. Library files were not saved again.

That check exposed an actual R2 `list` error 10058 during a concurrent system
read; a serialized read succeeded. [Cloudflare's error reference](https://developers.cloudflare.com/r2/api/error-codes/)
and [R2 limits](https://developers.cloudflare.com/r2/platform/limits/)
document this rate limit, including one write per second to an object key.
The transport now retries only explicit 10058 storage rejections with bounded
backoff and unchanged compare-and-swap conditions, and writes heartbeat updates
at most every five seconds. It never reruns a native operation. Nine transport
tests pass, including a per-key rate-limited claim/complete flow, the exact `list`
error, bounded retries and immediate propagation of unrelated faults.
The owner-private Site version 10 deployed from
`85b5201beb9318b1167e3a1c91cd7e415241abe4`, deployment
`appgdep_6ad7ca183f04819187a6e615a394f9e0`; native package and UI resource
remain unchanged. [Issue #5](https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin/issues/5)
tracks the fix and live verification. This observed error does not establish
the cause of earlier relay-session losses.

Live verification of Site version 10 passed after renewing the temporary
acceptance pairing: four concurrent companion draft/state/system/capability reads
all returned HTTP 200 in 13.183 seconds, with no returned 10058 errors. Native
0.4.4, ready models, both recordings with favorites false, zero jobs and complete
shared draft revision 2 were unchanged. The same native worker remained alive;
exactly one replacement detached relay was online. The final check was
20:14:53 UTC and the renewed pairing expires at 21:10:32.532 UTC.

A separate upstream receipt accounting discrepancy is tracked in
[Riff #33](https://github.com/Flip-Engineering/riff/issues/33). Individual source,
AR and NAR sizes/hashes and canonical provenance verified correctly; the receipt's
aggregate size differs from the referenced payload total by 16 MiB. This did not
prevent installation or selection.


Site version 11 also handles observed R2 internal error 10001 for `get` and
`list` only. Ambiguous write failures are not retried. Ten transport tests pass.
A fresh actual Chat studio then played the original recording with an animated
custom visualizer and no error toast. Earlier failed visualization evidence is
retained; recovery is an observed later check, not a reinterpretation of failure.
Deployment: `appgdep_6ad7cd53823c81919f0c9ab029ede7ab`.

Version 0.4.5 replaces unavailable native Qwen/MLX writing and OpenRouter with
**ChatGPT session**. Phrase shuffle remains available. YuE2 still composes native
melody/chord scores and renders audio. The adapter routes legacy writer selections
to the current session and prevents a Surprise-song job from queuing a separate
writer when lyrics are missing. Complete the lyrics in Chat before generation.
Writing, score revision and review controls prepare a visible, selectable request
for Chat; WAV export does the same. Copy/paste is explicit because the actual
host's component message API stalled. Preparing a request does not send it or
publish a file. Normal conversation export remains the demonstrated file route.
The plugin has no OpenRouter credential setup. These changes are downstream only;
upstream Riff and its desktop writer remain untouched.

The browser fixture passed original studio navigation, score composition and
editing, library playback, LoRA workflows, Chat request handoffs and video export.
Neural inference in that fixture is a declared test double. Backend tests cover
legacy-writer redirection, no external review dispatch, existing-lyrics generation
and refusal to queue an implicit separate writer. The actual Chat install and
visible controls are verified separately below.

The owner-private Site version 13 uses resource
`ui://riff/studio/adapter-v0.2.6.html`, source
`c37932932c42625df580fb7fd7c6678e3c0faed8`, deployment
`appgdep_6ad7cfbae9648191bc1edf0d2f08d0c3`. The existing primary plugin identity
was updated to 0.4.5. This keeps the cloud runtime in each user's Chat environment;
the Site supplies the UI and transport, and the homelab is not a runtime backend.

Actual cloud 0.4.5 verification returned ready state, both existing recordings,
zero queued jobs and review provider **ChatGPT session**. A direct app call to
`riff_write` with `idea_engine=chatgpt` returned a prepared `write` request,
without a provider call or draft edit. This verifies the installed adapter's
session routing, rather than merely a label change in the browser.

Actual Chat panel acceptance of 0.4.5 also passed: the writer selector contains
only **ChatGPT session** and **Phrase shuffle / instant**. Local-writer controls
and OpenRouter settings are hidden. The existing recording played normally.
A trusted WAV-to-Chat click opened the new request dialog without starting a Chat
run or saving a duplicate Library file. This host denied the clipboard API;
the dialog kept the complete text selected and displayed the keyboard-copy
instruction, rather than falsely reporting that it had copied or sent anything.
The full Studio was left open. Automatic host file/message delivery remains #4.


### 0.4.6: automatic panel follow-up

The earlier manual handoff is superseded. Live inspection showed ChatGPT's
follow-up extension requires a synchronous user event. Riff previously awaited
initialization, shared-draft saves and context updates before sending, which
lost that authorization. A direct trusted-click test in Chat produced
`PANEL_HANDOFF_OK` without a pasted message.

The studio now invokes the documented sendFollowUpMessage API before any await.
Writing includes the current editor snapshot and expected shared revision in the
request; ChatGPT saves its result with that revision, and the studio applies it
if the artist has not edited further. Reviews include the recording ID and
focus, and WAV export requests publication of the original cloud-workspace file.
No message is retried through another transport after an uncertain result.
Browser acceptance enforces the trusted-event requirement on writing, inspiration
and review controls. Native inference, model storage and pairing are unchanged.


Installed 0.4.6 acceptance used the same primary plugin identity and Site v14.
The actual Studio displayed **Send to ChatGPT** and no copy/paste dialog. After
clarifying an earlier test-conversation instruction to keep the draft unchanged,
a fresh trusted click sent the editor snapshot automatically. ChatGPT saved it
from revision 3 to 4 and replied `AUTOMATIC_STUDIO_ROUNDTRIP_OK`; the live editor
showed “ChatGPT’s draft changes are now in the editor.” Its existing title was
preserved. The native worker remained the existing 0.4.5 process; this UI change
did not require native compilation or replacing music models.


The installed **WAV to Chat** button also completed automatically: Chat returned
**Download riff-original-a006eb3c.wav**, backed by the existing Library file
`libfile_2453c3769a6081919871f43f11234cf4`. It reused the earlier successful
publication, without another save or music generation. The draft remained at
revision 4. A separate trusted-click diagnostic using shared `ui/message` also
returned `MCP_HANDOFF_OK`; the earlier failures do not establish that this host
lacks component messaging. The temporary diagnostic button was removed.

The returned Library link opened the file viewer; its **Download file** control
saved the original WAV locally. ffprobe confirmed 0.998667 seconds of 48 kHz,
stereo PCM audio (191,788 bytes), without audio checksum verification. The host
file viewer reports no WAV preview; playback remains available in the Studio.
