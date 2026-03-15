# Phase 1 Implementation Notes

This document captures the full Phase 1 thinking, architecture, code layout, runtime behavior, and teammate-facing context for the live multimodal decorator shell.

## Phase 1 Goal

Phase 1 exists to make the product feel beyond-text. The user should be able to speak, show the room, hear the agent answer in voice, interrupt naturally, and feel like they are talking to a specific decorator persona rather than a generic assistant.

## What Phase 1 Had To Deliver

- voice input
- spoken output
- room video or snapshot ingestion
- interruption support
- frontend live interface
- orchestrator persona prompts
- room-scan guidance prompts

## What We Chose To Build

We intentionally implemented Phase 1 as a browser-first live shell with periodic room snapshots instead of full continuous video upload.

Why:

- periodic JPEG snapshots are much simpler and cheaper to make reliable in a hackathon setting
- the user still gets a live camera preview in the browser
- the agent still receives fresh visual context often enough to comment on visible room features
- this keeps the stack manageable while preserving the key Phase 1 experience

## High-Level Architecture

Browser demo:

- microphone capture
- camera preview
- transcript panel
- interrupt controls
- playback of spoken agent audio

FastAPI backend:

- `POST /api/live/session` creates a live session
- `WS /api/live/ws/{session_id}` bridges browser events to ADK Live
- `/demo` serves the static frontend
- `/healthz` and `/config` expose runtime diagnostics

ADK + Vertex AI Live:

- `Runner.run_live(...)` powers the conversation
- a `LiveRequestQueue` streams user audio, text, and snapshots
- the agent is a single `LlmAgent` configured as a decorator persona

Persistence:

- Firestore stores live session metadata and event logs
- Cloud Storage stores room snapshots under `sessions/{session_id}/snapshots/...`

## Main Design Decisions

### 1. Single Live Coordinator Instead Of Multi-Agent Routing

Phase 1 uses one live-facing `LlmAgent` instead of the earlier placeholder subagent flow.

Why:

- live conversations need low latency
- routing logic adds complexity before the demo experience is stable
- a single decorator persona is enough for the acceptance criteria

### 2. Snapshot-Based Vision Instead Of Full Video Streaming

The browser camera stays live locally, but the backend receives periodic JPEG snapshots.

Why:

- easier debugging
- smaller payloads
- enough visual context for room commentary and scan guidance

### 3. Audio-First With Transcript Support

The backend requests spoken responses from the Live API and also keeps audio transcription enabled so the UI can show text.

Why:

- the experience needs to feel voice-first
- transcript visibility helps debugging and usability
- text in the panel makes interruptions easier to understand

### 4. Browser Fallbacks For Demo Robustness

We added browser-side fallbacks because hackathon demos need resilience:

- browser speech recognition can help with local transcript visibility
- browser speech synthesis can speak final agent text if live PCM audio is not heard
- anti-self-listening logic reduces the chance of the agent hearing its own intro

These are support layers around the main Live API path, not the primary architecture.

## Runtime Flow

### Session Creation

1. The frontend calls `POST /api/live/session`.
2. The backend creates an in-memory ADK session.
3. Firestore gets a `live_sessions/{session_id}` document.
4. The client receives:
   - `session_id`
   - `websocket_url`
   - `snapshot_interval_ms`

### Live WebSocket

The frontend opens `WS /api/live/ws/{session_id}` and sends one of the following message types:

- `text`
- `audio`
- `snapshot`
- `interrupt`
- `end_turn`

The backend forwards these to ADK Live using `LiveRequestQueue`.

### Agent Intro Primer

When a live session starts, the backend primes the first turn so the agent:

- introduces itself as the decorator
- asks for one useful room angle
- keeps the intro short enough to interrupt

This was added because the acceptance criteria called for a distinct decorator persona and scan-guidance behavior from the start, not only after the user asks something explicit.

### Visual Context

When the camera is enabled:

- the browser shows the live preview locally
- every `SNAPSHOT_INTERVAL_MS`, a JPEG snapshot is captured
- the snapshot is sent over the WebSocket
- the backend uploads it to GCS
- Firestore stores snapshot metadata
- the agent can use the visual context in the live session

### Interruptions

Interruptions work on two levels:

- explicit interrupt button
- natural barge-in when the user starts speaking

Client-side playback is cleared immediately so interruption feels fast, even before the backend has fully processed the change.

## Agent Persona And Prompting

The Phase 1 decorator persona is intentionally specific:

- warm
- playful
- opinionated
- short-spoken
- visually grounded

The prompt also forces scan guidance behavior:

- ask for one room angle at a time
- describe only what can actually be observed
- label guesses as guesses
- avoid pretending to see anything not provided

This prompt lives in `agents/instructions.md`, and runtime context is appended from `services/live_runtime.py`.

## Files Added Or Edited In Phase 1

### Core Runtime

- `main.py`
  - serves `/demo`
  - exposes `POST /api/live/session`
  - exposes `WS /api/live/ws/{session_id}`
  - translates browser messages to ADK live requests

- `services/live_runtime.py`
  - owns the `Runner`
  - owns the `LiveRequestQueue`
  - builds `RunConfig`
  - forwards ADK live events to the browser
  - stores live-session metadata in memory
  - saves snapshot metadata and observations

- `services/__init__.py`
  - marks the services package and documents the live-runtime-facing Cloud helpers

### Configuration

- `config.py`
  - adds Phase 1 voice and snapshot settings
  - uses `gemini-live-2.5-flash-native-audio`

- `.env.example`
  - documents the Phase 1 environment variables

- `.env`
  - local developer environment values

### Agent And Prompts

- `agents/agent.py`
  - uses a single live-facing `LlmAgent`
  - loads dynamic instructions from runtime context

- `agents/instructions.md`
  - defines the decorator persona
  - defines room-scan guidance
  - defines observation rules

- `subagents/subagent1/agent_factory.py`
  - keeps the placeholder research subagent aligned with the current live model configuration
  - prevents stale model defaults if the older routing path is reused later

- `subagents/subagent2/agent_factory.py`
  - keeps the placeholder response-design subagent aligned with the current live model configuration
  - prevents stale model defaults if the older routing path is reused later

### Tools

- `tools/tool1.py`
  - persists snapshot observations worth remembering

- `tools/tool2.py`
  - exposes live session context to the agent

- `tools/__init__.py`
  - exports the Phase 1 live tool surface for clean imports

- `loader.py`
  - loads the Phase 1 toolset for the agent

### Persistence

- `services/firestore_store.py`
  - creates live session documents
  - updates session fields
  - appends lightweight event logs

- `services/storage_store.py`
  - saves snapshots to Cloud Storage

### Frontend

- `static/demo.html`
  - live demo UI

- `static/demo.css`
  - Phase 1 visual design

- `static/demo.js`
  - session creation
  - WebSocket handling
  - mic capture
  - camera snapshot capture
  - transcript rendering
  - interrupt behavior
  - browser speech fallbacks
  - anti-self-listening protection

- `static/audio-recorder-worklet.js`
  - captures microphone audio
  - downsamples to 16 kHz PCM

- `static/audio-player-worklet.js`
  - plays streamed 24 kHz PCM audio

### Docs

- `README.md`
  - teammate-facing Phase 1 setup, bootstrapping, and validation guide

- `PHASE1.md`
  - full implementation notes, tradeoffs, file map, and runtime behavior reference

## Message Contract

### Client To Server

- `{"type":"text","text":"..."}`
- `{"type":"audio","mime_type":"audio/pcm;rate=16000","data":"..."}`
- `{"type":"snapshot","mime_type":"image/jpeg","data":"...","timestamp_ms":123}`
- `{"type":"interrupt"}`
- `{"type":"end_turn"}`

### Server To Client

- `{"type":"partial_text","text":"..."}`
- `{"type":"agent_text","text":"..."}`
- `{"type":"audio","mime_type":"audio/pcm","data":"..."}`
- `{"type":"turn_state","turn_complete":true,"interrupted":false}`
- `{"type":"status","state":"...","detail":"..."}`

## Known Runtime Behaviors

### Spoken Output

Primary path:

- the Live API returns PCM audio
- the browser plays it through the audio worklet

Fallback path:

- if final agent text is available but audio is not heard, the browser can speak it using `speechSynthesis`

### Voice Input

Primary path:

- the browser streams 16 kHz PCM mic audio to the backend

Support path:

- browser speech recognition can help the UI show transcript text

### Self-Listening Protection

This came up during testing. The agent intro could sometimes be picked up by the mic and treated as user input.

We mitigated it by:

- enabling echo cancellation
- enabling noise suppression
- enabling auto gain control
- pausing browser speech recognition while the agent is speaking
- ignoring low-level mic audio during agent playback
- still allowing stronger barge-in for intentional interruptions

## Acceptance Criteria Mapping

### User can speak instead of typing

Implemented via microphone capture, PCM streaming, turn closing, and transcript support.

### Agent can respond in voice

Implemented via Vertex AI Live native audio output and browser PCM playback.

### User can interrupt the agent naturally

Implemented via explicit interrupt control plus local playback clearing and live turn interruption behavior.

### Agent maintains a distinct decorator persona

Implemented via the Phase 1 live persona prompt and the intro primer.

### Agent can comment on visible room features

Implemented via periodic room snapshots, live session context, and observation-constrained prompting.

## Common Debugging Notes

### If the live model connection fails

Use:

- `ADK_LIVE_MODEL=gemini-live-2.5-flash-native-audio`

Do not use the older `gemini-2.5-flash-live-001` value for Vertex AI Live in this project.

### If the agent does not speak

Check:

- the browser audio is not muted
- the session stays connected
- WebSocket messages include agent events
- the model is the native-audio Live model

### If the agent hears itself

First try:

- hard refresh the page
- keep speakers lower
- prefer headphones for final demos if the room is noisy

The code already includes anti-self-listening protections, but acoustic environments still matter.

## What Phase 1 Does Not Try To Solve

Phase 1 intentionally does not include:

- inspiration search
- shopping flows
- full redesign generation
- continuous video streaming to the model
- production-grade distributed session state

Those are later-phase concerns.

## Recommended Team Usage

Use `README.md` for teammate bootstrapping and run steps.

Use this file when someone needs:

- the architecture story
- the reasoning behind the Phase 1 design
- the file map
- the runtime/debugging notes
- the exact boundaries of what Phase 1 is and is not
