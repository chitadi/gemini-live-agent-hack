# Live Room Decorator Agent Roadmap

## Overview

This project is a Google Cloud Native live multimodal interior-design agent built with:
- `ADK` for orchestration
- `Vertex AI` for live multimodal reasoning and generation tools
- `Cloud Run` for backend hosting
- `Firestore` for application metadata and session state
- `Cloud Storage` for room images, inspiration assets, and generated renders

The product goal is to create a room-decorating agent that:
- sees the room through camera input
- hears the user through voice input
- speaks back with a distinct interior-designer persona
- asks useful style questions
- infers design direction when the user is unsure
- generates redesign images
- handles interruptions naturally
- iterates on feedback like "I don't like that lamp"
- finds matching products and emails links

This roadmap is optimized for the hackathon judging criteria:
- `Google Cloud Native`
- `Innovation & Multimodal User Experience`
- `Beyond Text`
- `Interruption handling`
- `Distinct persona and voice`

---

## North Star

Build an experience that feels like talking to a fun interior designer, not chatting with a text bot.

The ideal user experience is:
1. The user speaks and shows the room.
2. The agent looks at the space, asks natural follow-up questions, and reacts in voice.
3. The agent infers a style direction even if the user has weak design vocabulary.
4. The agent produces a visual redesign of the room.
5. The user interrupts freely and iterates live.
6. The agent eventually finds real products that match the design and emails the links.

---

## Core Product Principles

### 1. Voice-first, not chat-first

The interaction should be centered around speech and camera input. Text can exist as support, but it should not feel like a standard chatbot.

### 2. Multimodal understanding

The agent should combine:
- spoken intent
- visible room context
- prior feedback
- saved inspiration and design history

### 3. Interruption-friendly conversation

The user should be able to interrupt at any point and redirect the conversation naturally.

### 4. Strong persona

The agent should feel like a fun interior designer:
- playful
- confident
- visually observant
- lightly opinionated
- concise in speech

### 5. Practical output

The end result should not stop at inspiration. It should move toward:
- redesigned room visuals
- iterative edits
- purchasable product suggestions

---

## Target Architecture

### Cloud stack

- `Cloud Run` for the main FastAPI + ADK backend
- `Vertex AI` for live multimodal interaction and model-backed tool calls
- `Firestore` for structured app/session/design state
- `Cloud Storage` for all room images, inspiration assets, and generated renders
- `Secret Manager` for external provider credentials if needed

### Why this stack

This gives a clean Google Cloud Native story:
- ADK is the agent framework
- Vertex AI is the model platform
- Cloud Run is the hosted backend
- Firestore is the session/data store
- Cloud Storage is the media store

This directly supports the hackathon requirement that the backend be robustly hosted on Google Cloud and that the project meaningfully use ADK and/or the Google GenAI stack.

---

## Agent System

### Root orchestrator

The root orchestrator is the main live-facing agent.

Responsibilities:
- own the live conversation
- maintain the fun interior-designer persona
- ask style and room questions
- manage interruptions and turn state
- decide when to reuse stored results
- decide when to rerun inspiration retrieval
- route between decorator, generator, and fetcher
- decide whether to edit an existing render or generate a new one

This should be a custom ADK agent rather than a simple `LlmAgent`, because the workflow includes confidence checks, branching, persistence-aware logic, and repeat loops.

### Decorator subagent

Responsibilities:
- convert user intent and room context into a design brief
- retrieve inspiration
- tag inspiration images
- infer theme, palette, furniture direction, and room vibe
- store inspiration records for later reuse

### Generator subagent

Responsibilities:
- generate the initial redesigned room image
- edit the existing redesign after user feedback
- preserve room geometry and key constraints where appropriate
- avoid reinventing the whole room when only a local change is requested

### Fetcher subagent

Responsibilities:
- identify likely purchasable items from the accepted design
- search for close product matches
- rank results by confidence
- email a shopping list with URLs

### Optional validator subagent

Responsibilities:
- check whether a newly generated image still matches:
  - room constraints
  - chosen style
  - recent feedback
- catch bad or off-theme generations before showing them

---

## Tools

Planned tools:
- `capture_room_frames`
- `analyze_room_snapshot`
- `style_interview`
- `search_inspiration`
- `tag_inspiration_image`
- `store_design_records`
- `generate_redesign_image`
- `edit_redesign_image`
- `search_products`
- `send_product_email`

### Tool usage philosophy

ADK should handle:
- orchestration
- subagent routing
- live streaming
- shared state
- session flow

Focused model/tool calls should handle:
- vision analysis
- image tagging
- image generation
- image editing
- product matching support

### Important ADK constraint

Agents that need tools should not rely on `output_schema`, because structured output mode disables tool use. Use tools, shared state, and stored records instead.

---

## Persistence Design

### Firestore

Firestore stores structured metadata such as:
- users
- sessions
- room profiles
- style profiles
- design briefs
- inspiration assets metadata
- feedback events
- renders metadata
- product matches
- email/send status

### Cloud Storage

Cloud Storage stores large files such as:
- room snapshots
- inspiration images
- generated renders
- exported artifacts

### Why this split

Firestore is a strong fit for session-based app state and structured documents. Cloud Storage is the right place for heavy media artifacts.

---

## Multimodal UX Design

This is one of the most important parts of the roadmap because it maps directly to the hackathon scoring criteria.

### What "Beyond Text" means in this project

The product should not feel like:
- a text box with optional image upload
- a voice skin over a chatbot
- a static design generator

It should feel like:
- the user is speaking to a live decorator
- the decorator is looking at the room
- the decorator reacts naturally while the user moves the camera
- the user can interrupt naturally at any time
- the agent responds in voice and visuals, not only text

### Planned interaction style

The agent should guide the scan:
- "Show me the wall opposite the bed."
- "Pause on that corner for a second."
- "Tilt down so I can see the floor area."

The agent should make short live observations:
- "I can see the bed frame."
- "This room is narrow but has good natural light."
- "I think we can make this feel much warmer."

The agent should ask conversational style questions:
- "What vibe do you want this room to have?"
- "Do you want calm and minimal, or more expressive and layered?"
- "If you don't know the style name, tell me how you want the room to feel."

If the user is unsure, it should pivot:
- "Are you more into clean and quiet spaces or cozy and decorated ones?"
- "Do you want this room to feel energizing, calming, or luxurious?"
- "Would you rather impress guests or make this your comfort zone?"

---

## Interruption and Live Turn Handling

This is mandatory for the hackathon live-agent category.

### Requirements

- the user must be able to interrupt the agent mid-response
- the agent must stop speaking quickly
- the system must continue from the interruption naturally
- the interruption should update state, not restart the entire conversation

### How it is handled

At the backend:
- use ADK `Runner.run_live()`
- use `LiveRequestQueue`
- process `partial`, `turn_complete`, and `interrupted` events

At the frontend:
- stop local audio playback immediately on user barge-in
- stream the new audio to the backend without waiting for turn completion
- preserve visual context already captured in the session

At the orchestrator level:
- classify interruptions into:
  - clarification
  - preference change
  - navigation/control
  - full direction reset

Examples:
- "No, keep the bed."
- "Wait, I want warmer lighting."
- "Stop. Show me another option."
- "Actually, let's start from a more minimal vibe."

### Design implication

The agent should speak in short chunks and checkpoint reasoning frequently so interruption feels natural.

---

## Persona and Voice

### Persona

The default persona for v1 is:

**Fun interior designer**
- playful
- stylish
- sharp-eyed
- encouraging
- a little opinionated, but never pushy

### Persona behavior rules

- keep spoken responses concise
- sound like a real decorator, not a technical assistant
- use taste language sparingly and intentionally
- avoid sounding robotic or overly formal
- clearly say what is being observed, inferred, and suggested

### Voice

Use one consistent Vertex-compatible voice configured through `RunConfig.speech_config`.

The voice should feel:
- polished
- friendly
- premium enough to feel design-oriented
- calm under interruption

---

## Implementation Roadmap by Phase

## Phase 0. Foundation and Cloud Setup

### Goal

Establish the GCP-native base and working deployment skeleton.

### Deliverables

- Cloud Run backend scaffold
- Vertex AI configuration
- Firestore collection design
- Cloud Storage bucket design
- service account and IAM plan
- local + cloud environment configuration

### Acceptance criteria

- backend deploys on Cloud Run
- backend can authenticate to Vertex AI, Firestore, and Cloud Storage
- a live session can be created and persisted

---

## Phase 1. Live Multimodal Shell and Persona

### Goal

Build the live decorator shell so the product already feels beyond-text.

### Deliverables

- voice input
- spoken output
- room video/snapshot ingestion
- interruption support
- frontend live interface
- orchestrator persona prompts
- room-scan guidance prompts

### Implementation focus

- ADK live streaming setup
- handling `partial`, `turn_complete`, and `interrupted` events
- client-side barge-in behavior
- voice-first interaction
- first-pass fun interior-designer persona

### Acceptance criteria

- user can speak instead of typing
- agent can respond in voice
- user can interrupt the agent naturally
- agent maintains a distinct decorator persona
- agent can comment on visible room features

---

## Phase 2. Style Discovery and Decorator Agent

### Goal

Turn room context and conversation into a structured design direction.

### Deliverables

- decorator subagent
- style discovery prompts
- room-style confidence scoring
- inspiration-provider abstraction
- inspiration tagging logic
- Firestore persistence for style and inspiration data

### Implementation focus

- style questions first
- personality/lifestyle fallback when the user is unsure
- tentative style inference from room context
- ranked inspiration bundles
- reusable inspiration metadata

### Acceptance criteria

- agent can build a design brief even with vague user input
- decorator returns tagged inspiration candidates
- inspiration results are stored and reusable

---

## Phase 3. Generator Agent and First Redesign

### Goal

Produce the first visually convincing room redesign.

### Deliverables

- generator subagent
- prompt strategy for preserving room constraints
- initial redesign generation flow
- render storage and versioning

### Implementation focus

- combine room image(s), design brief, and room constraints
- preserve room geometry unless explicitly changed
- store generated renders in Cloud Storage
- store render metadata in Firestore

### Acceptance criteria

- first redesign image is generated successfully
- render reflects style direction
- render is linked to the correct session and design state

---

## Phase 4. Feedback Loop and Edit-In-Place

### Goal

Support natural back-and-forth iteration without restarting from zero.

### Deliverables

- feedback classification
- edit-existing-render workflow
- retrieval confidence logic
- fallback rerun of decorator when needed

### Implementation focus

Classify feedback into:
- local edit
- broader style shift
- control command
- restart

Behavior:
- local edit -> modify the current render
- style shift -> check stored inspiration/design records
- low-confidence reuse -> rerun decorator before generating again

### Acceptance criteria

- "I don't like the lamp" edits the current render
- "Make it more boho" can trigger a new design path
- session state remains coherent across revisions

---

## Phase 5. Fetcher Agent and Shopping Links

### Goal

Turn an approved design into a useful shopping output.

### Deliverables

- fetcher subagent
- item extraction flow
- product search and ranking
- email delivery

### Implementation focus

- derive item candidates from final render plus inspiration metadata
- search for similar products
- rank by confidence
- email product links instead of attempting autonomous checkout

### Acceptance criteria

- accepted design produces a shopping-list email
- email contains links and confidence information
- results are saved in Firestore

---

## Phase 6. Demo Polish for Hackathon Judging

### Goal

Maximize score on the actual rubric.

### Deliverables

- polished live demo flow
- stronger persona behavior
- visible multimodal moments
- explicit GCP-native architecture story
- graceful fallbacks for weak scans or vague style input

### Implementation focus

- strong opening interaction
- visible room scan and spoken observations
- intentional demo of interruption/barge-in
- concise explanation of design reasoning
- explicit mention of ADK, Vertex AI, Cloud Run, Firestore, and Cloud Storage in the pitch

### Acceptance criteria

- demo clearly shows "see, hear, and speak"
- interruption handling is stable enough to show live
- persona feels memorable
- judges can clearly see the Google Cloud Native backend story

---

## Phase 7. Stretch Goals

### Goal

Explore higher-risk features without blocking MVP.

### Stretch items

- snapshot-based room overlay experiments
- low-FPS pseudo-live object placement
- stronger visual similarity search using embeddings
- cross-session inspiration memory
- more retailer-specific product matching adapters

### Important constraint

True AR-grade live overlay should not be treated as an MVP requirement.

---

## Feasibility Summary

### Clearly feasible in MVP

- live voice/video room intake
- natural questioning and style discovery
- interruption-friendly conversation
- inspiration retrieval and tagging
- initial redesign image generation
- iterative edit loop
- product-link email delivery

### Feasible with caveats

- Pinterest as a data source
- visually near-identical product matching
- reliable reuse of prior designs based on confidence scoring

### Not reliable enough for MVP

- true live overlay of objects in a stable, AR-like way
- autonomous ordering and checkout
- fully accurate room measurement from casual phone video alone

---

## Testing and Success Criteria

### Core technical tests

- live session creation
- interruption handling
- room frame ingestion
- decorator persistence
- redesign generation
- render editing
- shopping email generation

### Hackathon acceptance scenarios

- user speaks and shows the room with minimal typing
- agent asks good style questions and infers a direction when needed
- user interrupts the agent and the conversation continues naturally
- agent produces an initial redesign and at least one revision
- final design produces a product-link email
- deployed backend clearly runs on Google Cloud services

---

## Assumptions and Defaults

- backend: `Vertex AI first`
- hosting: `Cloud Run`
- persistence: `Firestore + Cloud Storage`
- orchestration: `ADK`
- persona: `fun interior designer`
- UX priority: live voice/video interaction over text chat
- visual priority: redesign generation and editing before live overlay
- shopping scope: links plus email only
- inspiration retrieval: provider abstraction with Pinterest as optional, not mandatory
