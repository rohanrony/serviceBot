# Portal Frontend Specification (VoiceAI)

This document specifies the architecture, UI designs, and integration contracts for the VoiceAI Business Configuration Portal and Dashboard frontend.

---

## 1. Architecture & Static Assets Serving

To ensure simplicity, lightweight operation, and zero external deployment dependencies, the portal frontend is structured as a **Single Page Application (SPA)** served directly by the FastAPI web server.

- **FastAPI Routing Setup**: 
  - Static files are served from `serviceBot/static/` using `fastapi.staticfiles.StaticFiles` mounted at `/portal`.
  - The HTML entry point is located at `serviceBot/static/index.html`.
  - Main styling is defined in `serviceBot/static/style.css`.
  - Frontend interactive logic and API querying is defined in `serviceBot/static/app.js`.

- **API Integration**:
  - All operations leverage the `fetch()` API to query JSON endpoints defined in `/api/v1/portal/...`.

---

## 2. Visual Design System

The portal frontend follows a modern, high-end, responsive dark-themed design system.

### 2.1 CSS Design Tokens (Theme Variables)
```css
:root {
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-display: 'Outfit', sans-serif;

  /* HSL Tailored Color Palette */
  --bg-main: hsl(222, 47%, 11%);        /* Very dark blue-gray */
  --bg-sidebar: hsl(222, 47%, 7%);      /* Deeper blackish-blue */
  --bg-card: hsla(217, 33%, 17%, 0.7);  /* Semi-transparent glass container */
  --border-card: hsla(217, 33%, 25%, 0.4);
  
  --color-primary: hsl(210, 100%, 60%);   /* Vibrant electric blue */
  --color-success: hsl(145, 80%, 45%);   /* Emerald green */
  --color-warning: hsl(35, 90%, 55%);    /* Bright amber */
  --color-danger: hsl(0, 85%, 60%);      /* Coral red */
  
  --text-main: hsl(210, 40%, 98%);       /* Off-white */
  --text-muted: hsl(215, 20%, 65%);      /* Dim gray */
  --text-inverse: hsl(222, 47%, 11%);
  
  /* Layout constraints */
  --sidebar-width: 260px;
  --transition-smooth: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
```

### 2.2 Aesthetic Guidelines
- **Glassmorphic Cards**: Cards use background blur (`backdrop-filter: blur(12px)`) and semi-transparent borders.
- **Premium Typography**: Google Fonts integration (`Outfit` for page titles, `Inter` for regular text).
- **Interactive States**: Smooth scale-up and glowing box-shadows on hover for active items (cards, inputs, buttons).
- **Fade-in Animations**: Views use CSS Keyframe animations to fade and slide up when active:
```css
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

---

## 3. Screen Specifications & Views

The portal is composed of a responsive sidebar layout toggling 5 primary functional views:

```
┌────────────────────────────────────────────────────────┐
│  SIDEBAR      │  MAIN VIEWPORT                        │
│               │                                        │
│  Logo         │  [Tab Title / Page Name]               │
│               ├────────────────────────────────────────┤
│  Dashboard    │                                        │
│  Intents      │  [Dynamic Component Content]           │
│  Services     │                                        │
│  Knowledge    │                                        │
│  API Keys     │                                        │
└───────────────┴────────────────────────────────────────┘
```

### 3.1 View 1: Dashboard Overview
- **Metric Cards (Row)**:
  - **Total Calls**: Shows total incoming call counter.
  - **First Call Resolution (FCR)**: Percentage of calls resolved without handoff.
  - **Booked Appointments**: Total scheduled mock calendar slots.
  - **Service Requests**: Total captured auto tickets.
- **Call Logs Table**:
  - Columns: Timestamp, Customer Name, Phone, Actions (View Transcript).
  - Clicking a row slides in a **Detail Drawer** showing:
    - AI-generated brief call summary logs.
    - Full speech turn-by-turn conversation transcript.

### 3.2 View 2: Intent Configurator
- **Intent Cards Grid**:
  - Displays the 7 intents.
  - Allow businesses to edit the required parameters (e.g. checkbox required fields for new customer tickets vs status lookups).
  - Save button executes dynamic configurations API.

### 3.3 View 3: Service Manager
- **Services Data Table**:
  - Displays service pricing structure list.
- **Add Service Form**:
  - Input fields: Name, Description, Price Range, Duration (Minutes).
  - Triggers `POST /api/v1/portal/services` and refreshes table.

### 3.4 View 4: Knowledge Base (RAG)
- **Document Manager**:
  - Drag-and-drop file uploader area.
  - Displays uploaded documents and chunking status count.
  - Connects to `/api/v1/portal/kb/upload`.

### 3.5 View 5: Credentials & Voice Settings
- **Voice Configurations**:
  - Dropdown choosing LLM Models (OpenAI GPT-4, Claude 3.5).
  - Dropdown listing ElevenLabs voices fetched dynamically.
- **Secret Keys Inputs**:
  - Hides sensitive fields using password-style characters (`***`).
  - Inputs for: ElevenLabs API Key, ElevenLabs Agent ID, OpenAI Key, Anthropic Key, Twilio Token.
  - Submits keys to REST API to run encryption helper routines.

---

## 4. Integration Specifications

### 4.1 Script Operations (app.js)
```javascript
// Example fetch utility
async function apiCall(endpoint, options = {}) {
  const response = await fetch(endpoint, options);
  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`);
  }
  return response.json();
}
```

- **Interactive Tab Swapping**: Tab navigation toggles active visibility CSS classes (`.active`) on sections, preventing browser reloading and providing fluid transitions.
- **Form Submissions**: Listeners serialize user payloads, inject loading spinner widgets, block double submissions, and show temporary toast notifications upon API response.
