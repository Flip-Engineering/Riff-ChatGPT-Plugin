/* Host actions run after every ORIGINAL Riff module. The studio remains Riff. */
(function () {
  "use strict";
  const host = window.RiffHost;
  let revision = null, synced = null, incoming = null, polling = false, closed = false;
  let draftTimer, contextTimer, contextSignature = "", lastDeepLink = "";
  const signature = () => JSON.stringify(formRecipe());
  let hadLocalDraft = false;
  try { hadLocalDraft = !!localStorage.getItem("riff.draft"); } catch {}
  const initialForm = signature();
  const bar = document.createElement("section");
  bar.setAttribute("aria-label", "ChatGPT integration");
  bar.id = "riff-chatgpt-host-bar";
  const status = document.createElement("span");
  status.id = "riff-chatgpt-status";
  status.setAttribute("role", "status");
  status.textContent = "Connecting your studio…";
  const row = document.createElement("div"); row.className = "riff-host-actions";
  const context = () => ({ app: "Riff", selectedTrackId: selected?.id || null,
    selectedTrackTitle: selected?.title || null, recipe: formRecipe(), sharedDraftRevision: revision,
    view: document.querySelector("#library-view").hidden ? "studio" : "library",
    draftConflict: !!incoming });
  const announce = text => { status.textContent = text; };
  host.on("error", error => announce(error.message));
  host.on("download", ({ name }) => announce(`Export ready: ${name}`));
  const handoff = document.createElement("dialog"); handoff.id = "riff-chat-request";
  handoff.setAttribute("aria-label", "Continue in ChatGPT");
  const handoffTitle = document.createElement("h2"); handoffTitle.textContent = "Continue in ChatGPT";
  const handoffHelp = document.createElement("p"); handoffHelp.textContent = "Copy this request, close this window, and paste it into the chat.";
  const handoffText = document.createElement("textarea"); handoffText.id = "riff-chat-request-text";
  handoffText.setAttribute("aria-label", "Chat request"); handoffText.readOnly = true; handoffText.rows = 6;
  const copyRequest = document.createElement("button"); copyRequest.type = "button"; copyRequest.textContent = "Copy request";
  copyRequest.addEventListener("click", async () => {
    handoffText.focus(); handoffText.select();
    try { await navigator.clipboard.writeText(handoffText.value); copyRequest.textContent = "Copied"; }
    catch { copyRequest.textContent = "Press ⌘C or Ctrl+C to copy"; }
  });
  const closeHandoff = document.createElement("button"); closeHandoff.type = "button"; closeHandoff.textContent = "Close";
  closeHandoff.addEventListener("click", () => handoff.close());
  handoff.append(handoffTitle, handoffHelp, handoffText, copyRequest, closeHandoff); document.body.append(handoff);
  function prepareChatRequest(prompt) {
    handoffText.value = prompt; copyRequest.textContent = "Copy request";
    if (!handoff.open) handoff.showModal();
    handoffText.focus(); handoffText.select();
    announce("Request ready. Paste it into ChatGPT to continue.");
  }
  host.on("export-request", ({ prompt }) => prepareChatRequest(prompt));

  function remember() {
    try { localStorage.setItem("riff.chatgpt.shared", JSON.stringify({ revision, signature: synced })); } catch {}
  }
  function applyDraft(draft) {
    fillRecipe(draft.recipe); saveDraft();
    revision = draft.revision; synced = signature(); incoming = null;
    remember(); scheduleContext();
  }
  function acceptDraft(draft, initial = false) {
    if (!draft || !Number.isInteger(draft.revision) || !draft.recipe || typeof draft.recipe !== "object" || Array.isArray(draft.recipe)) {
      throw new Error("The studio returned an invalid shared draft.");
    }
    if (initial && revision === null) {
      let previous = null;
      try { previous = JSON.parse(localStorage.getItem("riff.chatgpt.shared") || "null"); } catch {}
      revision = draft.revision;
      if (Object.keys(draft.recipe).length && ((!hadLocalDraft && signature() === initialForm) || signature() === previous?.signature)) {
        applyDraft(draft); announce("Shared draft restored. Your studio is ready.");
      } else {
        synced = Object.keys(draft.recipe).length ? previous?.signature || null : signature();
        announce(Object.keys(draft.recipe).length && signature() !== synced
          ? "Your local draft is open. Restore the shared draft when you want to use it."
          : "Your studio is ready.");
      }
      scheduleContext(); return;
    }
    if (draft.revision === revision || draft.revision === incoming?.revision) return;
    if (signature() === synced) {
      applyDraft(draft); announce("ChatGPT’s draft changes are now in the editor.");
    } else {
      incoming = draft;
      announce("The shared draft changed while you were editing. Your edits are kept; restore the shared draft to use the new version.");
      scheduleContext();
    }
  }
  async function readDraft() {
    const result = await host.callTool("riff_get_draft", {});
    return result.structuredContent.body;
  }
  async function saveShared() {
    if (revision === null) throw new Error("Wait for the shared draft to connect before saving.");
    const recipe = formRecipe(), before = JSON.stringify(recipe);
    const result = await host.callTool("riff_save_draft", { recipe, expected_revision: revision });
    revision = result.structuredContent.body.revision;
    synced = before; incoming = null; remember(); scheduleContext();
    announce(signature() === before ? "Shared draft saved." : "Shared draft saved. Your newer edits remain in the editor.");
  }
  async function restoreShared() {
    const draft = await readDraft();
    if (!Object.keys(draft.recipe).length) throw new Error("No shared draft has been saved.");
    if (signature() !== synced && !window.confirm("Replace the editor’s current unsaved recipe with the shared draft?")) return;
    applyDraft(draft); announce("Shared draft restored.");
  }
  function action(label, id, perform) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "text-button"; button.id = id; button.textContent = label;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { await perform(); } catch (error) { announce(error.message); }
      finally { button.disabled = false; }
    });
    row.append(button); return button;
  }
  action("Save shared draft", "riff-save-shared", saveShared);
  action("Restore shared draft", "riff-restore-shared", restoreShared);
  action("Attach draft to chat", "riff-share-context", async () => {
    await host.shareContext(context()); announce("Current draft and selection attached to ChatGPT.");
  });
  const writing = document.createElement("form"); writing.id = "riff-chatgpt-writing"; writing.hidden = true;
  const label = document.createElement("label"); label.htmlFor = "riff-writing-request"; label.textContent = "What would you like to write or change?";
  const request = document.createElement("textarea"); request.id = label.htmlFor; request.rows = 2;
  request.placeholder = "Write a chorus, refine the sound, or change the melody…"; request.maxLength = 8000;
  const send = document.createElement("button"); send.type = "submit"; send.className = "secondary-button"; send.textContent = "Prepare Chat request";
  writing.append(label, request, send);
  action("Write with ChatGPT", "riff-write-with-chatgpt", () => { writing.hidden = !writing.hidden; if (!writing.hidden) request.focus(); });
  writing.addEventListener("submit", async event => {
    event.preventDefault();
    const prompt = request.value.trim();
    if (!prompt) { request.focus(); return; }
    send.disabled = true;
    try {
      await saveShared();
      await host.shareContext(context());
      prepareChatRequest(`In the current Riff draft: ${prompt}\n\nUse the attached Riff context. Read the shared draft and save the completed recipe with riff_save_draft and the current expected_revision so it returns to the studio. Keep unrelated creative settings. Generate audio only if I asked for it.`);
      writing.hidden = true;
    } catch (error) { announce(error.message); }
    finally { send.disabled = false; }
  });
  row.append(status); bar.append(row, writing); document.body.prepend(bar);
  const style = document.createElement("style");
  style.textContent = `#riff-chatgpt-host-bar{padding:10px clamp(12px,3vw,40px);border-bottom:1px solid var(--line,#d9d2cf);font:inherit;background:var(--paper,#faf7f1)}
  #riff-chat-request{width:min(580px,90vw);padding:24px;color:var(--ink,#252321);background:var(--paper,#faf7f1);border:1px solid var(--line,#d9d2cf);border-radius:12px}#riff-chat-request p{margin:12px 0}#riff-chat-request textarea{display:block;width:100%;box-sizing:border-box;margin:16px 0;padding:12px;font:inherit;color:inherit;background:transparent;border:1px solid var(--line,#d9d2cf);resize:vertical}#riff-chat-request button{margin-right:12px}
+  #riff-chatgpt-host-bar .riff-host-actions{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
+  #riff-chatgpt-host-bar button{font:inherit}#riff-chatgpt-host-bar [role=status]{flex:1 1 280px;font-size:.8rem;line-height:1.5;opacity:.8}
+  #riff-chatgpt-writing:not([hidden]){display:grid;grid-template-columns:1fr auto;gap:8px 12px;margin-top:12px;max-width:850px}
+  #riff-chatgpt-writing label{grid-column:1/-1;font-size:.85rem}#riff-chatgpt-writing textarea{min-width:0;resize:vertical;padding:10px;background:transparent;color:inherit;border:1px solid var(--line,#bfb7b5);border-radius:6px;font:inherit}
+  .riff-media-load{display:block;margin:4px 0 10px}@media(max-width:500px){#riff-chatgpt-writing:not([hidden]){grid-template-columns:1fr}}`.replace(/^\+/gm, "");
  document.head.append(style);
  const reference = document.querySelector("#copy-listening-link");
  if (reference) reference.textContent = "Copy recording reference";

  function scheduleContext() {
    clearTimeout(contextTimer);
    contextTimer = setTimeout(async () => {
      if (closed) return;
      const value = context(), next = JSON.stringify(value);
      if (contextSignature === next) return;
      try { await host.shareContext(value, { explicit: false }); contextSignature = next; }
      catch { /* Explicit attach remains available on hosts without background context. */ }
    }, 500);
  }
  document.addEventListener("input", event => {
    if (event.target.closest("#riff-chatgpt-host-bar, #review-settings, #system-dialog")) return;
    scheduleContext();
  });
  document.addEventListener("change", scheduleContext);
  host.on("navigation", scheduleContext);
  async function pollShared() {
    if (polling || closed) return;
    polling = true;
    try { acceptDraft(await readDraft(), revision === null); }
    catch (error) { if (revision === null) announce(error.message); }
    finally { polling = false; if (!closed) draftTimer = setTimeout(pollShared, document.hidden ? 8000 : 3000); }
  }
  async function applyDeepLink() {
    const id = host.preferredTrack();
    if (!id || id === lastDeepLink || firstLoad || !state.tracks.some(track => track.id === id)) return;
    lastDeepLink = id; await selectTrack(id); showView("studio", false); scheduleContext();
  }
  host.on("host-context", applyDeepLink);
  host.on("tool-input", applyDeepLink);
  host.on("tool-result", result => {
    const body = result?.structuredContent?.body || result?.structuredContent;
    if (body?.draft) acceptDraft(body.draft, revision === null);
    else if (body?.recipe && Number.isInteger(body.revision)) acceptDraft(body, revision === null);
    applyDeepLink();
  });

  // Native media requests bypass fetch. Keep preview transfers behind an explicit
  // user action, then give the original audio/video controls a local media URL.
  function attachPreviews(root) {
    for (const media of root.querySelectorAll?.("[data-riff-media-path]:not([data-riff-preview-ready])") || []) {
      media.dataset.riffPreviewReady = "1";
      const button = document.createElement("button"); button.type = "button";
      button.className = "text-button riff-media-load"; button.textContent = "Load and play preview";
      button.addEventListener("click", async () => {
        button.disabled = true; button.textContent = "Loading preview…";
        try {
          await host.useMedia(media, media.dataset.riffMediaPath, true);
          button.remove();
        } catch (error) { button.disabled = false; button.textContent = "Try preview again"; announce(error.message); }
      });
      media.after(button);
    }
  }
  const mediaObserver = new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) if (node.nodeType === 1) attachPreviews(node.parentElement || node);
  });
  mediaObserver.observe(document.body, { childList: true, subtree: true });
  attachPreviews(document);
  document.addEventListener("click", async event => {
    const anchor = event.target.closest?.("a[href]");
    const path = anchor?.getAttribute("href");
    if (!path) return;
    if (path.startsWith("/api/") || ((path.startsWith("blob:") || path.startsWith("data:")) && anchor.hasAttribute("download"))) {
      event.preventDefault(); event.stopImmediatePropagation();
      try { await host.downloadLink(anchor); } catch (error) { announce(error.message); }
    } else if (/^https?:\/\//.test(path)) {
      event.preventDefault(); event.stopImmediatePropagation();
      try { await host.openLink(path); } catch (error) { announce(error.message); }
    }
  }, true);

  // The managed plugin has a bundled engine. Retain the original settings dialog
  // and adapt only settings whose meaning differs from a desktop installation.
  function managedSettings(next) {
    const system = next.maintenance;
    if (!system?.plugin_managed) return;
    document.querySelector("#setup-engine").textContent = "Download music models";
    document.querySelector("#setup-description").textContent = "Download the pinned music model and audio decoder. Verified downloads resume and stay available for your next session.";
    document.querySelector("#engine-backend").closest("div").hidden = true;
    document.querySelector("#engine-binary").closest("details").hidden = true;
    const updates = document.querySelector("#system-version").closest("section");
    for (const element of updates.children) element.hidden = true;
    updates.hidden = true;
    const cancel = document.querySelector("#cancel-update");
    document.querySelector("#setup-engine").parentElement.append(cancel);
    cancel.textContent = "Cancel download";
    cancel.hidden = system.task.status !== "running" || system.task.action !== "setup";
    const progress = document.querySelector("#system-progress");
    if (Number.isFinite(system.task.progress)) { progress.max = 1; progress.value = system.task.progress; }
    const requirements = document.querySelector("#setup-requirements");
    if (system.model_terms) {
      const terms = document.createElement("p");
      terms.textContent = `Music model terms: ${system.model_terms.license}. `;
      const link = document.createElement("a"); link.href = system.model_terms.url; link.textContent = "Read model terms"; terms.append(link); requirements.append(terms);
    }
  }
  function writerAvailability() {
    if (typeof state.engine.writer_ready !== "boolean") return;
    const selector = document.querySelector("#idea-engine"), option = selector.querySelector('[value="ai"]');
    option.disabled = !state.engine.writer_ready;
    option.textContent = state.engine.writer_ready ? "Local AI writer" : "Local AI writer · unavailable";
    if (!ideaBusy) {
      const unavailable = !state.engine.writer_ready && selector.value === "ai";
      for (const id of ["surprise", "spark", "shuffle-lyrics"]) document.getElementById(id).disabled = unavailable;
      if (unavailable) document.querySelector("#writer-status").textContent = "Use Write with ChatGPT or choose another idea source.";
      else if (document.querySelector("#writer-status").textContent.startsWith("Use Write with ChatGPT")) document.querySelector("#writer-status").textContent = "Ready for an idea";
    }
  }
  document.querySelector("#idea-engine").addEventListener("change", writerAvailability);
  const originalRender = window.RiffControls.render;
  window.RiffControls.render = function (next) { originalRender(next); managedSettings(next); writerAvailability(); };
  host.on("api", ({ path }) => {
    if (path === "/api/state" || path === "/api/system") setTimeout(() => { managedSettings(state); writerAvailability(); applyDeepLink(); }, 0);
  });
  host.ready.then(() => {
    if (!host.hostCapabilities.downloadFile) {
      const wav = document.querySelector("#download");
      wav.textContent = "WAV to Chat";
      wav.title = "Ask ChatGPT to export the original WAV to your Library";
    }
    if (host.lastToolResult) host.emit("tool-result", host.lastToolResult);
    pollShared(); scheduleContext();
  }).catch(error => announce(error.message));
  async function cleanup() {
    closed = true; clearTimeout(draftTimer); clearTimeout(contextTimer); clearTimeout(pollTimer);
    mediaObserver.disconnect(); saveDraft(); audio.pause();
    for (const media of document.querySelectorAll("audio,video")) media.pause();
    if (typeof videoExport !== "undefined" && videoExport) await cancelVideoExport().catch(() => {});
  }
  host.on("teardown", cleanup);
  window.addEventListener("pagehide", () => { cleanup().finally(() => host.close()); }, { once: true });
})();
