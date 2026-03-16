const elements = {
  startButton: document.getElementById("startButton"),
  voiceModeButton: document.getElementById("voiceModeButton"),
  textModeButton: document.getElementById("textModeButton"),
  micButton: document.getElementById("micButton"),
  cameraButton: document.getElementById("cameraButton"),
  photoUploadInput: document.getElementById("photoUploadInput"),
  endTurnButton: document.getElementById("endTurnButton"),
  textForm: document.getElementById("textForm"),
  textInput: document.getElementById("textInput"),
  sendTextButton: document.getElementById("sendTextButton"),
  inputModeHint: document.getElementById("inputModeHint"),
  sessionBadge: document.getElementById("sessionBadge"),
  statusBadge: document.getElementById("statusBadge"),
  snapshotBadge: document.getElementById("snapshotBadge"),
  mainLayout: document.getElementById("mainLayout"),
  cameraPanel: document.getElementById("cameraPanel"),
  cameraStatus: document.getElementById("cameraStatus"),
  connectionStatus: document.getElementById("connectionStatus"),
  snapshotIntervalLabel: document.getElementById("snapshotIntervalLabel"),
  transcriptList: document.getElementById("transcriptList"),
  inspirationStatus: document.getElementById("inspirationStatus"),
  inspirationQueries: document.getElementById("inspirationQueries"),
  inspirationGallery: document.getElementById("inspirationGallery"),
  cameraPreview: document.getElementById("cameraPreview"),
  snapshotCanvas: document.getElementById("snapshotCanvas"),
};

const state = {
  sessionId: null,
  websocket: null,
  websocketUrl: null,
  inputMode: "voice",
  snapshotIntervalMs: 2500,
  snapshotCount: 0,
  currentAgentBubble: null,
  currentUserBubble: null,
  recorderContext: null,
  recorderNode: null,
  recorderSource: null,
  recorderSink: null,
  micStream: null,
  micEnabled: false,
  userAudioOpen: false,
  silenceTimerId: null,
  speechRecognition: null,
  speechRecognitionShouldRun: false,
  browserTranscriptBuffer: "",
  serverHeardUserThisTurn: false,
  fallbackTextSentThisTurn: false,
  lastCommittedUserText: "",
  currentTurnHasServerAudio: false,
  agentSpeechFallbackEnabled: "speechSynthesis" in window,
  agentSpeechFallbackTimerId: null,
  agentSpeaking: false,
  playerContext: null,
  playerNode: null,
  cameraStream: null,
  cameraEnabled: false,
  snapshotTimerId: null,
  lastRenderUrl: "",
  renderHistory: [],
  lastAgentCommittedText: "",
  responseCycleId: 0,
  lastAgentCommitCycleId: -1,
  seenSystemMessagesThisCycle: new Set(),
  userSpeakingSignalSent: false,
};

const SPEECH_LEVEL_THRESHOLD = 120;
const USER_TURN_SILENCE_MS = 850;
const AGENT_FALLBACK_DELAY_MS = 300;

function setStatus(text, detail = "") {
  elements.statusBadge.textContent = detail ? `${text}: ${detail}` : text;
}

function setConnectionStatus(text) {
  elements.connectionStatus.textContent = text;
}

function setInspirationStatus(text) {
  elements.inspirationStatus.textContent = text;
}

function syncInputControls() {
  const sessionReady = Boolean(state.sessionId);
  const voiceMode = state.inputMode === "voice";

  elements.voiceModeButton.classList.toggle("is-active", voiceMode);
  elements.voiceModeButton.setAttribute("aria-pressed", String(voiceMode));
  elements.textModeButton.classList.toggle("is-active", !voiceMode);
  elements.textModeButton.setAttribute("aria-pressed", String(!voiceMode));

  elements.micButton.disabled = !sessionReady || !voiceMode;
  elements.cameraButton.disabled = !sessionReady;
  elements.endTurnButton.disabled = true;
  elements.textInput.disabled = !sessionReady;
  elements.sendTextButton.disabled = !sessionReady;
  elements.mainLayout.classList.toggle("text-only", !voiceMode);
  elements.cameraPanel.classList.toggle("is-hidden", !voiceMode);
  elements.inputModeHint.textContent = voiceMode
    ? "Voice mode keeps listening and speaking separate, so the agent audio is not streamed back as user input."
    : "Text mode keeps the mic off and lets you drive each turn manually.";
}

function startResponseCycle() {
  state.responseCycleId += 1;
  state.lastAgentCommittedText = "";
  state.lastAgentCommitCycleId = -1;
  state.seenSystemMessagesThisCycle = new Set();
}

function clearChildren(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function renderInspirationQueries(queries) {
  clearChildren(elements.inspirationQueries);

  for (const query of queries) {
    const chip = document.createElement("span");
    chip.className = "query-chip";
    chip.textContent = query;
    elements.inspirationQueries.appendChild(chip);
  }
}

function getInspirationResultHost(result) {
  const candidateUrl = result.sourcePageUrl || result.imageUrl || result.thumbnailUrl;
  if (!candidateUrl) {
    return "Saved source";
  }

  try {
    return new URL(candidateUrl).hostname.replace(/^www\./, "");
  } catch (_error) {
    return "Saved source";
  }
}

function createInspirationImageFallback(result) {
  const fallback = document.createElement("div");
  fallback.className = "inspiration-image-fallback";

  const label = document.createElement("strong");
  label.textContent = "Preview unavailable";

  const host = document.createElement("span");
  host.textContent = getInspirationResultHost(result);

  fallback.appendChild(label);
  fallback.appendChild(host);
  return fallback;
}

function buildGeneratedRenderUrl(session, objectPath) {
  const sessionId = String(session.session_id || state.sessionId || "").trim();
  const resolvedObjectPath = encodeURIComponent(
    String(objectPath || session.latest_generated_render_path || "").trim()
  );
  if (!sessionId || !resolvedObjectPath) {
    return "";
  }
  return `/api/live/session/${sessionId}/generated-render?object_path=${resolvedObjectPath}`;
}

function renderGeneratedRender(session) {
  const renderUrl = buildGeneratedRenderUrl(
    session,
    session.latest_generated_render_path
  );
  if (!renderUrl) {
    return false;
  }
  if (state.lastRenderUrl !== renderUrl) {
    state.lastRenderUrl = renderUrl;
    state.renderHistory = [
      {
        url: renderUrl,
        objectPath: String(session.latest_generated_render_path || "").trim(),
      },
      ...state.renderHistory.filter((entry) => entry.url !== renderUrl),
    ].slice(0, 6);
  }
  setInspirationStatus("Final redesign ready");
  clearChildren(elements.inspirationGallery);

  state.renderHistory.forEach((entry, index) => {
    const card = document.createElement("article");
    card.className = "generated-render-card";

    const link = document.createElement("a");
    link.href = entry.url;
    link.target = "_blank";
    link.rel = "noreferrer noopener";

    const image = document.createElement("img");
    image.src = entry.url;
    image.alt = index === 0 ? "Latest redesigned room render" : "Previous redesigned room render";
    image.loading = index === 0 ? "eager" : "lazy";
    image.addEventListener("error", () => {
      if (card.isConnected) {
        renderInspirationEmptyState(
          "One of the redesigned images was saved, but it could not be loaded into the board."
        );
      }
    });

    const copy = document.createElement("div");
    copy.className = "generated-render-copy";

    const version = document.createElement("span");
    version.className = "generated-render-version";
    version.textContent = index === 0 ? "Latest version" : `Version ${state.renderHistory.length - index}`;

    const title = document.createElement("strong");
    title.textContent = index === 0 ? "Redesigned room render" : "Previous redesign";

    const meta = document.createElement("span");
    meta.textContent = "Generated from saved snapshots and inspiration references";

    copy.appendChild(version);
    copy.appendChild(title);
    copy.appendChild(meta);
    link.appendChild(image);
    link.appendChild(copy);
    card.appendChild(link);
    elements.inspirationGallery.appendChild(card);
  });
  return true;
}

function renderInspirationGallery(session) {
  const queries = Array.isArray(session.latest_inspiration_search_queries)
    ? session.latest_inspiration_search_queries
    : [];
  const resultsByQuery = Array.isArray(session.latest_inspiration_image_results)
    ? session.latest_inspiration_image_results
    : [];

  renderInspirationQueries(queries);
  if (session.latest_generated_render_available) {
    if (renderGeneratedRender(session)) {
      return;
    }
  }

  const flattenedResults = [];
  for (const group of resultsByQuery) {
    if (!group || typeof group !== "object") {
      continue;
    }

    const query = String(group.query || "").trim();
    const results = Array.isArray(group.results) ? group.results : [];
    for (const result of results) {
      if (!result || typeof result !== "object") {
        continue;
      }
      flattenedResults.push({
        query: String(result.query || query).trim(),
        title: String(result.title || "").trim(),
        imageUrl: String(result.image_url || "").trim(),
        thumbnailUrl: String(result.thumbnail_url || "").trim(),
        sourcePageUrl: String(result.source_page_url || "").trim(),
        displayLink: String(result.display_link || "").trim(),
      });
    }
  }

  const visibleResults = flattenedResults
    .filter((result) => result.imageUrl || result.thumbnailUrl)
    .slice(0, 8);

  clearChildren(elements.inspirationGallery);

  if (visibleResults.length) {
    if (
      session.latest_tool_name === "generate_redesign_image" &&
      session.latest_tool_status === "started"
    ) {
      setInspirationStatus("Generating redesign...");
    } else if (
      session.latest_tool_name === "generate_redesign_image" &&
      session.latest_tool_status === "failed"
    ) {
      setInspirationStatus("Redesign failed");
    } else {
      setInspirationStatus(
        `Showing ${visibleResults.length} saved image${visibleResults.length === 1 ? "" : "s"}`
      );
    }

    for (const result of visibleResults) {
      const card = document.createElement("article");
      card.className = "inspiration-card";

      const link = document.createElement("a");
      link.href = result.sourcePageUrl || result.imageUrl || result.thumbnailUrl || "#";
      link.target = "_blank";
      link.rel = "noreferrer noopener";

      const image = document.createElement("img");
      image.src = result.thumbnailUrl || result.imageUrl;
      image.alt = result.title || result.query || "Saved inspiration image";
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      image.addEventListener("error", () => {
        if (image.src !== result.imageUrl && result.imageUrl) {
          image.src = result.imageUrl;
          return;
        }
        if (image.isConnected) {
          image.replaceWith(createInspirationImageFallback(result));
        }
      });

      const copy = document.createElement("div");
      copy.className = "inspiration-copy";

      const title = document.createElement("strong");
      title.textContent = result.title || result.query || "Inspiration result";

      const meta = document.createElement("span");
      meta.textContent = result.query || result.displayLink || "Saved result";

      copy.appendChild(title);
      copy.appendChild(meta);
      link.appendChild(image);
      link.appendChild(copy);
      card.appendChild(link);
      elements.inspirationGallery.appendChild(card);
    }

    return;
  }

  if (
    session.latest_tool_name === "generate_redesign_image" &&
    session.latest_tool_status === "started"
  ) {
    setInspirationStatus("Generating redesign...");
    renderInspirationEmptyState(
      "Inspiration matches are saved. The generator is turning them into a redesigned room image now."
    );
    return;
  }

  if (
    session.latest_tool_name === "generate_redesign_image" &&
    session.latest_tool_status === "failed"
  ) {
    setInspirationStatus("Redesign failed");
    renderInspirationEmptyState(
      session.latest_tool_detail ||
        "The redesign generator failed before it could save a final image."
    );
    return;
  }

  if (
    session.latest_tool_name === "search_inspiration_images" &&
    session.latest_tool_status === "failed"
  ) {
    setInspirationStatus("Image search failed");
    renderInspirationEmptyState(
      session.latest_tool_detail ||
        "The image-search tool failed before it could save results."
    );
    return;
  }

  if (
    session.latest_tool_name === "search_inspiration_images" &&
    session.latest_tool_status === "started"
  ) {
    setInspirationStatus("Searching...");
    renderInspirationEmptyState(
      "The agent is currently searching for image matches. Results should appear here automatically."
    );
    return;
  }

  if (queries.length) {
    setInspirationStatus("Plan saved, waiting for image matches");
    renderInspirationEmptyState(
      "Search queries are saved for this brief, but no image matches have been saved yet."
    );
    return;
  }

  setInspirationStatus("Waiting for inspiration images");
  renderInspirationEmptyState(
    "Start a redesign brief and let the agent save image matches. The strongest few results will show up here."
  );
}

function renderInspirationEmptyState(message) {
  clearChildren(elements.inspirationGallery);
  const empty = document.createElement("article");
  empty.className = "inspiration-empty";
  empty.textContent = message;
  elements.inspirationGallery.appendChild(empty);
}

function applySessionContext(session) {
  if (!session || typeof session !== "object") {
    return;
  }

  if (typeof session.snapshot_count === "number" && session.snapshot_count >= 0) {
    state.snapshotCount = session.snapshot_count;
    updateSnapshotCount();
  }

  renderInspirationGallery(session);
}

function appendBubble(role, text, { append = false } = {}) {
  if (!text) {
    return;
  }

  const cleaned = String(text).trim();
  if (!cleaned) {
    return;
  }

  if (role === "system") {
    const fingerprint = `${role}:${cleaned}`;
    if (state.seenSystemMessagesThisCycle.has(fingerprint)) {
      return;
    }
    state.seenSystemMessagesThisCycle.add(fingerprint);
  }

  if (role === "agent" && append && state.currentAgentBubble) {
    state.currentAgentBubble.querySelector("span").textContent += cleaned;
    elements.transcriptList.scrollTop = elements.transcriptList.scrollHeight;
    return;
  }

  const bubble = document.createElement("article");
  bubble.className = `bubble ${role}`;
  bubble.innerHTML = `<small>${role}</small><span></span>`;
  bubble.querySelector("span").textContent = cleaned;
  elements.transcriptList.appendChild(bubble);

  if (role === "agent") {
    state.currentAgentBubble = bubble;
  }

  elements.transcriptList.scrollTop = elements.transcriptList.scrollHeight;
}

function appendImageBubble(role, imageUrl, caption) {
  if (!imageUrl) {
    return;
  }

  const bubble = document.createElement("article");
  bubble.className = `bubble ${role} image-bubble`;
  bubble.innerHTML = `<small>${role}</small><img alt="" /><span></span>`;
  bubble.querySelector("img").src = imageUrl;
  bubble.querySelector("img").alt = caption || `${role} image`;
  bubble.querySelector("span").textContent = caption || "";
  elements.transcriptList.appendChild(bubble);
  elements.transcriptList.scrollTop = elements.transcriptList.scrollHeight;
}

function showAgentNarration(text, { speak = true } = {}) {
  const cleaned = String(text || "").trim();
  if (!cleaned) {
    return;
  }
  appendBubble("agent", cleaned);
  if (speak) {
    queueAgentSpeechFallback(cleaned, { force: true });
  }
}

function normalizeAgentText(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function tokenizeAgentText(text) {
  return normalizeAgentText(text)
    .split(" ")
    .filter((token) => token.length > 2);
}

function areAgentRepliesNearDuplicate(previousText, nextText) {
  const previousNormalized = normalizeAgentText(previousText);
  const nextNormalized = normalizeAgentText(nextText);
  if (!previousNormalized || !nextNormalized) {
    return false;
  }
  if (previousNormalized === nextNormalized) {
    return true;
  }
  if (
    previousNormalized.includes(nextNormalized) ||
    nextNormalized.includes(previousNormalized)
  ) {
    return true;
  }

  const previousTokens = new Set(tokenizeAgentText(previousText));
  const nextTokens = new Set(tokenizeAgentText(nextText));
  if (!previousTokens.size || !nextTokens.size) {
    return false;
  }

  let overlap = 0;
  for (const token of nextTokens) {
    if (previousTokens.has(token)) {
      overlap += 1;
    }
  }

  const overlapRatio = overlap / Math.min(previousTokens.size, nextTokens.size);
  return overlapRatio >= 0.7;
}

function commitAgentText(text) {
  const cleaned = String(text || "").trim();
  if (!cleaned) {
    return;
  }

  if (
    state.lastAgentCommitCycleId === state.responseCycleId &&
    state.lastAgentCommittedText &&
    areAgentRepliesNearDuplicate(state.lastAgentCommittedText, cleaned)
  ) {
    if (state.currentAgentBubble) {
      state.currentAgentBubble.querySelector("span").textContent = cleaned;
    }
    state.lastAgentCommittedText = cleaned;
    return;
  }

  if (state.currentAgentBubble) {
    state.currentAgentBubble.querySelector("span").textContent = cleaned;
  } else {
    appendBubble("agent", cleaned);
  }
  state.lastAgentCommittedText = cleaned;
  state.lastAgentCommitCycleId = state.responseCycleId;
}

function closeCurrentAgentBubble() {
  state.currentAgentBubble = null;
}

function resetAgentTurnState() {
  state.currentTurnHasServerAudio = false;
  state.agentSpeaking = false;
}

function setAgentSpeaking(active) {
  state.agentSpeaking = active;

  if (active) {
    // Browser speech recognition fallback is intentionally disabled so
    // ADK/Vertex owns turn detection and transcription during the live demo.
    // stopSpeechRecognition();
    return;
  }

  if (state.micEnabled && !state.userAudioOpen) {
    // startSpeechRecognition();
  }
}

function upsertCurrentUserBubble(text) {
  if (!text) {
    return;
  }

  if (!state.currentUserBubble) {
    const bubble = document.createElement("article");
    bubble.className = "bubble user";
    bubble.innerHTML = "<small>user</small><span></span>";
    bubble.querySelector("span").textContent = text;
    elements.transcriptList.appendChild(bubble);
    state.currentUserBubble = bubble;
  } else {
    state.currentUserBubble.querySelector("span").textContent = text;
  }

  elements.transcriptList.scrollTop = elements.transcriptList.scrollHeight;
}

function finalizeCurrentUserBubble(text) {
  if (!text) {
    return;
  }

  if (state.currentUserBubble) {
    state.currentUserBubble.querySelector("span").textContent = text;
    state.currentUserBubble = null;
  } else {
    appendBubble("user", text);
  }
}

function closeCurrentUserBubble() {
  state.currentUserBubble = null;
}

function getSpeechRecognitionClass() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function resetBrowserTurnState() {
  state.browserTranscriptBuffer = "";
  state.serverHeardUserThisTurn = false;
  state.fallbackTextSentThisTurn = false;
  state.lastCommittedUserText = "";
}

// Browser speech recognition fallback is retained for reference, but disabled.
function maybeFinalizeUserTranscript(text) {
  const cleaned = text.trim();
  if (!cleaned) {
    return false;
  }

  if (cleaned === state.lastCommittedUserText) {
    return true;
  }

  finalizeCurrentUserBubble(cleaned);
  state.lastCommittedUserText = cleaned;
  return true;
}

function maybeSendBrowserTranscriptFallback() {
  const cleaned = state.browserTranscriptBuffer.trim();
  if (!cleaned || state.serverHeardUserThisTurn || state.fallbackTextSentThisTurn) {
    return false;
  }

  state.fallbackTextSentThisTurn = true;
  maybeFinalizeUserTranscript(cleaned);
  sendJson({ type: "text", text: cleaned });
  setStatus("Thinking", "Using browser speech transcript fallback.");
  return true;
}

function ensureSpeechRecognition() {
  if (state.speechRecognition) {
    return state.speechRecognition;
  }

  const SpeechRecognitionClass = getSpeechRecognitionClass();
  if (!SpeechRecognitionClass) {
    return null;
  }

  const recognition = new SpeechRecognitionClass();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = navigator.language || "en-US";

  recognition.onresult = (event) => {
    if (state.agentSpeaking) {
      return;
    }

    let interimTranscript = "";

    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const transcript = result[0]?.transcript?.trim();
      if (!transcript) {
        continue;
      }

      if (result.isFinal) {
        state.browserTranscriptBuffer = [
          state.browserTranscriptBuffer,
          transcript,
        ]
          .filter(Boolean)
          .join(" ")
          .trim();
      } else {
        interimTranscript = [interimTranscript, transcript].filter(Boolean).join(" ").trim();
      }
    }

    const displayText = [state.browserTranscriptBuffer, interimTranscript]
      .filter(Boolean)
      .join(" ")
      .trim();

    if (displayText) {
      upsertCurrentUserBubble(displayText);
      setStatus("Listening", displayText);
    }
  };

  recognition.onerror = (event) => {
    if (!state.micEnabled) {
      return;
    }

    if (event.error === "aborted" || event.error === "no-speech") {
      return;
    }

    appendBubble(
      "system",
      `Browser speech recognition error: ${event.error}. Audio streaming is still active.`
    );
  };

  recognition.onend = () => {
    if (!state.speechRecognitionShouldRun) {
      return;
    }

    try {
      recognition.start();
    } catch (_error) {
      window.setTimeout(() => {
        if (!state.speechRecognitionShouldRun) {
          return;
        }
        try {
          recognition.start();
        } catch (_retryError) {
          // Leave audio streaming active even if browser speech recognition cannot restart.
        }
      }, 250);
    }
  };

  state.speechRecognition = recognition;
  return recognition;
}

function startSpeechRecognition() {
  const recognition = ensureSpeechRecognition();
  if (!recognition) {
    return false;
  }

  state.speechRecognitionShouldRun = true;
  try {
    recognition.start();
  } catch (_error) {
    // Browsers throw if start is called while already active; restarting is handled in onend.
  }
  return true;
}

function stopSpeechRecognition() {
  state.speechRecognitionShouldRun = false;
  if (!state.speechRecognition) {
    return;
  }

  try {
    state.speechRecognition.stop();
  } catch (_error) {
    // Ignore teardown errors from browser speech recognition.
  }
}

function stopAgentSpeechFallback() {
  if (state.agentSpeechFallbackTimerId) {
    window.clearTimeout(state.agentSpeechFallbackTimerId);
    state.agentSpeechFallbackTimerId = null;
  }
  if (!window.speechSynthesis) {
    return;
  }
  window.speechSynthesis.cancel();
}

function speakAgentFallback(text, { force = false } = {}) {
  const cleaned = text.trim();
  if (
    !cleaned ||
    !state.agentSpeechFallbackEnabled ||
    (!force && state.currentTurnHasServerAudio) ||
    !window.speechSynthesis
  ) {
    return;
  }

  stopAgentSpeechFallback();
  setAgentSpeaking(true);
  const utterance = new SpeechSynthesisUtterance(cleaned);
  utterance.rate = 1;
  utterance.pitch = 1.02;
  utterance.lang = navigator.language || "en-US";
  utterance.onend = () => {
    if (force || !state.currentTurnHasServerAudio) {
      setAgentSpeaking(false);
    }
  };
  window.speechSynthesis.speak(utterance);
  setStatus("Responding", "Using browser speech fallback.");
}

function queueAgentSpeechFallback(text, { force = false } = {}) {
  stopAgentSpeechFallback();
  if (!text.trim()) {
    return;
  }

  state.agentSpeechFallbackTimerId = window.setTimeout(() => {
    state.agentSpeechFallbackTimerId = null;
    if (!force && state.currentTurnHasServerAudio) {
      return;
    }
    speakAgentFallback(text, { force });
  }, AGENT_FALLBACK_DELAY_MS);
}

function clearSilenceTimer() {
  if (state.silenceTimerId) {
    window.clearTimeout(state.silenceTimerId);
    state.silenceTimerId = null;
  }
}

function scheduleUserTurnClose() {
  clearSilenceTimer();
  state.silenceTimerId = window.setTimeout(() => {
    state.silenceTimerId = null;
    state.userAudioOpen = false;
    if (state.userSpeakingSignalSent) {
      sendJson({ type: "stop_speaking" });
      state.userSpeakingSignalSent = false;
    }
    closeCurrentUserBubble();
    if (!state.agentSpeaking) {
      setStatus("Thinking");
    }
  }, USER_TURN_SILENCE_MS);
}

function updateSnapshotCount() {
  elements.snapshotBadge.textContent = `Snapshots: ${state.snapshotCount}`;
}

function setControlsEnabled(enabled) {
  if (!enabled) {
    elements.micButton.disabled = true;
    elements.cameraButton.disabled = true;
    elements.endTurnButton.disabled = true;
    elements.textInput.disabled = true;
    elements.sendTextButton.disabled = true;
    return;
  }

  syncInputControls();
}

async function setInputMode(mode) {
  state.inputMode = mode === "text" ? "text" : "voice";
  if (state.inputMode === "text" && state.micEnabled) {
    await disableMicrophone();
  }
  if (state.inputMode === "text" && state.cameraEnabled) {
    stopCamera();
  }
  if (state.inputMode === "text" && state.userSpeakingSignalSent) {
    sendJson({ type: "stop_speaking" });
    state.userSpeakingSignalSent = false;
  }
  syncInputControls();
}

function sendJson(payload) {
  if (state.websocket && state.websocket.readyState === WebSocket.OPEN) {
    state.websocket.send(JSON.stringify(payload));
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";

  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return window.btoa(binary);
}

function base64ToArrayBuffer(base64) {
  const binaryString = window.atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i += 1) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

function getPcmLevel(buffer) {
  const samples = new Int16Array(buffer);
  if (!samples.length) {
    return 0;
  }

  let total = 0;
  for (let i = 0; i < samples.length; i += 1) {
    total += Math.abs(samples[i]);
  }
  return total / samples.length;
}

async function ensurePlayer() {
  if (state.playerContext && state.playerNode) {
    if (state.playerContext.state === "suspended") {
      await state.playerContext.resume();
    }
    return;
  }

  state.playerContext = new AudioContext({ sampleRate: 24000 });
  await state.playerContext.audioWorklet.addModule("/static/audio-player-worklet.js");
  state.playerNode = new AudioWorkletNode(state.playerContext, "pcm-player");
  state.playerNode.connect(state.playerContext.destination);
}

async function ensureRecorder() {
  if (state.recorderContext && state.recorderNode && state.micStream) {
    if (state.recorderContext.state === "suspended") {
      await state.recorderContext.resume();
    }
    return;
  }

  state.micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    },
    video: false,
  });
  state.recorderContext = new AudioContext({ sampleRate: 16000 });
  await state.recorderContext.audioWorklet.addModule(
    "/static/audio-recorder-worklet.js"
  );

  state.recorderSource = state.recorderContext.createMediaStreamSource(
    state.micStream
  );
  state.recorderNode = new AudioWorkletNode(
    state.recorderContext,
    "pcm-recorder",
    {
      processorOptions: {
        targetSampleRate: 16000,
      },
    }
  );
  state.recorderSink = state.recorderContext.createGain();
  state.recorderSink.gain.value = 0;
  state.recorderNode.port.onmessage = (event) => {
    if (!state.micEnabled || !event.data) {
      return;
    }

    const audioLevel = getPcmLevel(event.data);
    const isSpeaking = audioLevel > SPEECH_LEVEL_THRESHOLD;

    if (state.agentSpeaking) {
      return;
    }

    if (isSpeaking && !state.userAudioOpen) {
      state.userAudioOpen = true;
      startResponseCycle();
      resetBrowserTurnState();
      setStatus("Listening");
      if (!state.userSpeakingSignalSent) {
        sendJson({ type: "start_speaking" });
        state.userSpeakingSignalSent = true;
      }
    }

    if (!state.userAudioOpen) {
      return;
    }

    if (isSpeaking) {
      setStatus("Listening");
    }
    scheduleUserTurnClose();

    sendJson({
      type: "audio",
      mime_type: "audio/pcm;rate=16000",
      data: arrayBufferToBase64(event.data),
    });
  };

  state.recorderSource.connect(state.recorderNode);
  state.recorderNode.connect(state.recorderSink);
  state.recorderSink.connect(state.recorderContext.destination);
}

function clearAgentAudio() {
  closeCurrentAgentBubble();
  setAgentSpeaking(false);
  stopAgentSpeechFallback();
  if (state.playerNode) {
    state.playerNode.port.postMessage({ type: "clear" });
  }
}

async function startDemo() {
  if (state.sessionId && state.websocket && state.websocket.readyState === WebSocket.OPEN) {
    return;
  }

  setStatus("Starting");
  await ensurePlayer();

  const response = await fetch("/api/live/session", { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to create live session: ${response.status}`);
  }

  const payload = await response.json();
  state.sessionId = payload.session_id;
  state.websocketUrl = payload.websocket_url;
  state.snapshotIntervalMs = payload.snapshot_interval_ms;
  state.snapshotCount = 0;

  elements.sessionBadge.textContent = `Session: ${state.sessionId.slice(0, 8)}`;
  elements.snapshotIntervalLabel.textContent = `Snapshot cadence: ${state.snapshotIntervalMs} ms`;
  updateSnapshotCount();

  connectWebSocket();
}

function connectWebSocket() {
  if (!state.websocketUrl) {
    return;
  }

  if (state.websocket && state.websocket.readyState === WebSocket.OPEN) {
    state.websocket.close();
  }

  state.websocket = new WebSocket(state.websocketUrl);

  state.websocket.onopen = () => {
    setStatus("Connected");
    setConnectionStatus("Connected");
    setControlsEnabled(true);
    showAgentNarration("Live session connected. Enable the mic or camera to begin.");
  };

  state.websocket.onmessage = async (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "partial_text") {
      setStatus("Responding");
      return;
    }

    if (message.type === "session_context") {
      applySessionContext(message.session);
      return;
    }

    if (message.type === "agent_note") {
      showAgentNarration(message.text);
      return;
    }

    if (message.type === "agent_text") {
      commitAgentText(message.text);
      if (!state.currentTurnHasServerAudio) {
        queueAgentSpeechFallback(message.text);
      }
      return;
    }

    if (message.type === "audio") {
      await ensurePlayer();
      state.userAudioOpen = false;
      if (state.userSpeakingSignalSent) {
        state.userSpeakingSignalSent = false;
      }
      clearSilenceTimer();
      state.currentTurnHasServerAudio = true;
      setAgentSpeaking(true);
      stopAgentSpeechFallback();
      const pcmBuffer = base64ToArrayBuffer(message.data);
      state.playerNode.port.postMessage(pcmBuffer, [pcmBuffer]);
      setStatus("Responding", "Playing live voice.");
      return;
    }

    if (message.type === "turn_state") {
      closeCurrentAgentBubble();
      closeCurrentUserBubble();
      state.userAudioOpen = false;
      clearSilenceTimer();
      resetBrowserTurnState();
      stopAgentSpeechFallback();
      setAgentSpeaking(false);
      resetAgentTurnState();
      const label = message.interrupted ? "Interrupted" : "Turn complete";
      setStatus(label);
      return;
    }

    if (message.type === "status") {
      handleStatusMessage(message);
    }
  };

  state.websocket.onclose = () => {
    setStatus("Disconnected");
    setConnectionStatus("Disconnected");
    setControlsEnabled(false);
    closeCurrentAgentBubble();
    closeCurrentUserBubble();
    stopAgentSpeechFallback();
    setAgentSpeaking(false);
    resetAgentTurnState();
    if (state.cameraEnabled) {
      stopCamera();
    }
    if (state.micEnabled) {
      state.micEnabled = false;
      state.userAudioOpen = false;
      resetBrowserTurnState();
      clearSilenceTimer();
      // stopSpeechRecognition();
      elements.micButton.textContent = "Enable Mic";
      if (state.recorderContext && state.recorderContext.state === "running") {
        state.recorderContext.suspend();
      }
    }
    syncInputControls();
  };

  state.websocket.onerror = () => {
    setStatus("WebSocket error");
  };
}

function handleStatusMessage(message) {
  const detail = message.detail || "";

  if (message.state === "connected") {
    showAgentNarration(detail);
  } else if (message.state === "snapshot_saved") {
    setStatus("Snapshot saved", detail);
  } else if (message.state === "user_transcript") {
    state.serverHeardUserThisTurn = true;
    state.userAudioOpen = false;
    maybeFinalizeUserTranscript(detail);
    setStatus("Thinking");
  } else if (message.state === "listening") {
    state.serverHeardUserThisTurn = true;
    upsertCurrentUserBubble(detail);
    setStatus("Listening", detail);
  } else if (message.state === "user_speaking") {
    clearAgentAudio();
    setStatus("Listening", detail);
  } else if (message.state === "user_stopped_speaking") {
    setStatus("Thinking", detail);
  } else if (message.state === "interrupt_hint") {
    stopAgentSpeechFallback();
    setAgentSpeaking(false);
    setStatus("Interrupt", detail);
  } else if (message.state === "turn_detection_auto") {
    setStatus("Auto turn detection", detail);
  } else if (message.state === "error") {
    showAgentNarration(`Error: ${detail}`, { speak: false });
    setStatus("Error", detail);
  } else if (message.state === "unsupported_message") {
    showAgentNarration(detail, { speak: false });
  } else {
    setStatus(message.state, detail);
  }
}

async function toggleMicrophone() {
  if (!state.sessionId) {
    await startDemo();
  }

  if (state.inputMode !== "voice") {
    setStatus("Text mode", "Switch back to voice mode to enable the mic.");
    return;
  }

  if (state.micEnabled) {
    await disableMicrophone();
    return;
  }

  await ensureRecorder();
  await state.recorderContext.resume();
  await ensurePlayer();
  if (state.playerContext.state === "suspended") {
    await state.playerContext.resume();
  }
  state.micEnabled = true;
  state.userAudioOpen = false;
  resetBrowserTurnState();
  if (!state.agentSpeaking) {
    // startSpeechRecognition();
  }
  elements.micButton.textContent = "Disable Mic";
  setStatus(
    "Mic live",
    `Speak naturally. Listening opens on your speech and pauses while the agent is talking. Input ${state.recorderContext.sampleRate} Hz -> 16000 Hz PCM.`
  );
}

async function disableMicrophone() {
  state.micEnabled = false;
  state.userAudioOpen = false;
  if (state.userSpeakingSignalSent) {
    sendJson({ type: "stop_speaking" });
    state.userSpeakingSignalSent = false;
  }
  // maybeSendBrowserTranscriptFallback();
  // stopSpeechRecognition();
  stopAgentSpeechFallback();
  resetBrowserTurnState();
  clearSilenceTimer();
  elements.micButton.textContent = "Enable Mic";
  if (state.recorderContext && state.recorderContext.state === "running") {
    await state.recorderContext.suspend();
  }
  setStatus("Mic off");
}

async function toggleCamera() {
  if (!state.sessionId) {
    await startDemo();
  }

  if (state.cameraEnabled) {
    stopCamera();
    return;
  }

  state.cameraStream = await navigator.mediaDevices.getUserMedia({
    video: {
      facingMode: { ideal: "environment" },
      width: { ideal: 1280 },
      height: { ideal: 720 },
    },
    audio: false,
  });
  elements.cameraPreview.srcObject = state.cameraStream;
  state.cameraEnabled = true;
  elements.cameraButton.textContent = "Disable Camera";
  elements.cameraStatus.textContent = "Camera live";

  await elements.cameraPreview.play();
  await captureSnapshot();
  state.snapshotTimerId = window.setInterval(
    captureSnapshot,
    state.snapshotIntervalMs
  );
}

function stopCamera() {
  state.cameraEnabled = false;
  elements.cameraButton.textContent = "Enable Camera";
  elements.cameraStatus.textContent = "Camera off";

  if (state.snapshotTimerId) {
    window.clearInterval(state.snapshotTimerId);
    state.snapshotTimerId = null;
  }

  if (state.cameraStream) {
    for (const track of state.cameraStream.getTracks()) {
      track.stop();
    }
    state.cameraStream = null;
  }

  elements.cameraPreview.srcObject = null;
  elements.cameraPreview.removeAttribute("src");
}

async function captureSnapshot() {
  if (
    !state.cameraEnabled ||
    !state.websocket ||
    state.websocket.readyState !== WebSocket.OPEN ||
    !elements.cameraPreview.videoWidth
  ) {
    return;
  }

  const canvas = elements.snapshotCanvas;
  const context = canvas.getContext("2d");
  const width = elements.cameraPreview.videoWidth;
  const height = elements.cameraPreview.videoHeight;
  canvas.width = width;
  canvas.height = height;
  context.drawImage(elements.cameraPreview, 0, 0, width, height);

  const blob = await new Promise((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", 0.76)
  );

  if (!blob) {
    return;
  }

  const buffer = await blob.arrayBuffer();
  state.snapshotCount += 1;
  updateSnapshotCount();

  sendJson({
    type: "snapshot",
    mime_type: "image/jpeg",
    timestamp_ms: Date.now(),
    is_primary_reference: state.snapshotCount === 1,
    source: "camera",
    data: arrayBufferToBase64(buffer),
  });
}

async function uploadReferencePhoto(file) {
  if (!file) {
    return;
  }

  if (!state.sessionId) {
    await startDemo();
  }

  const imageUrl = URL.createObjectURL(file);
  try {
    const image = await new Promise((resolve, reject) => {
      const preview = new Image();
      preview.onload = () => resolve(preview);
      preview.onerror = () => reject(new Error("Uploaded image could not be read."));
      preview.src = imageUrl;
    });

    const canvas = elements.snapshotCanvas;
    const context = canvas.getContext("2d");
    canvas.width = image.width;
    canvas.height = image.height;
    context.drawImage(image, 0, 0, image.width, image.height);
    elements.cameraPreview.srcObject = null;
    elements.cameraPreview.src = canvas.toDataURL("image/jpeg", 0.9);
    elements.cameraStatus.textContent = "Uploaded reference photo";

    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.9)
    );
    if (!blob) {
      throw new Error("Uploaded image could not be converted.");
    }

    const buffer = await blob.arrayBuffer();
    state.snapshotCount += 1;
    updateSnapshotCount();
    setStatus("Reference uploaded", "Using this photo as the primary render anchor.");
    showAgentNarration(
      "Primary room photo uploaded. The final render will stay anchored to this view."
    );
    appendImageBubble(
      "user",
      imageUrl,
      "Uploaded room reference. Use this exact view as the template for analysis and the final redesign."
    );
    sendJson({
      type: "snapshot",
      mime_type: "image/jpeg",
      timestamp_ms: Date.now(),
      is_primary_reference: true,
      source: "upload",
      data: arrayBufferToBase64(buffer),
    });
  } finally {
    elements.photoUploadInput.value = "";
  }
}

function sendTextMessage(text) {
  const cleaned = text.trim();
  if (!cleaned) {
    return;
  }

  startResponseCycle();
  clearAgentAudio();
  closeCurrentUserBubble();
  resetBrowserTurnState();
  appendBubble("user", cleaned);
  state.lastCommittedUserText = cleaned;
  setStatus("Thinking");
  sendJson({ type: "text", text: cleaned });
}

function bindEvents() {
  elements.startButton.addEventListener("click", async () => {
    try {
      await startDemo();
    } catch (error) {
      showAgentNarration(String(error), { speak: false });
      setStatus("Start failed");
    }
  });

  elements.voiceModeButton.addEventListener("click", async () => {
    await setInputMode("voice");
  });

  elements.textModeButton.addEventListener("click", async () => {
    await setInputMode("text");
  });

  elements.micButton.addEventListener("click", async () => {
    try {
      await toggleMicrophone();
    } catch (error) {
      showAgentNarration(`Microphone error: ${error}`, { speak: false });
      setStatus("Mic error");
    }
  });

  elements.cameraButton.addEventListener("click", async () => {
    try {
      await toggleCamera();
    } catch (error) {
      showAgentNarration(`Camera error: ${error}`, { speak: false });
      setStatus("Camera error");
    }
  });

  elements.photoUploadInput.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    try {
      await uploadReferencePhoto(file);
    } catch (error) {
      showAgentNarration(`Upload error: ${error}`, { speak: false });
      setStatus("Upload error");
    }
  });

  elements.endTurnButton.addEventListener("click", async () => {
    setStatus("Auto turn detection", "Turns close automatically in the live model.");
  });

  elements.textForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendTextMessage(elements.textInput.value);
    elements.textInput.value = "";
  });
}

bindEvents();
syncInputControls();
