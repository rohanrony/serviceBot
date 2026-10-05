import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "/Users/rohanroy/Coding/voiceService";
const skillDir = "/Users/rohanroy/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const buildDir = path.join(workspaceDir, ".codex-build", "voiceai-sales-deck");
const stagingDir = path.join(buildDir, ".codex-finalizer");
const outputPath = path.join(workspaceDir, ".codex-output", "VoiceAI_sales_enablement_v4.pptx");
const heroPath = path.join(buildDir, "voiceai-hero.png");

const { resolvePresentationFont, finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(buildDir, { recursive: true });
await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(outputPath), { recursive: true });

const fontFamily = resolvePresentationFont();
const presentation = Presentation.create({
  slideSize: { width: 1280, height: 720 },
});

const C = {
  navy: "#071827",
  navy2: "#0D2B42",
  navy3: "#153B56",
  warm: "#F7F4EE",
  paper: "#FFFCF7",
  ink: "#102434",
  muted: "#526777",
  line: "#CBD7DC",
  teal: "#5FE1D2",
  tealDark: "#0E766E",
  aqua: "#B7FFF6",
  amber: "#F2C37B",
  coral: "#F39D84",
  white: "#FFFFFF",
};

function box(slide, position, fill, line = "none", geometry = "roundRect", name) {
  return slide.shapes.add({
    geometry,
    name,
    position,
    fill,
    line: { style: "solid", fill: line, width: line === "none" ? 0 : 1 },
    ...(geometry === "roundRect" ? { borderRadius: "rounded-xl" } : {}),
  });
}

function text(slide, value, position, style = {}, name) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    typeface: fontFamily,
    fontSize: 18,
    color: C.ink,
    autoFit: "shrinkTextOnOverflow",
    ...style,
  };
  return shape;
}

function line(slide, position, color, width = 1, name) {
  return slide.shapes.add({
    geometry: "line",
    name,
    position,
    fill: "none",
    line: { style: "solid", fill: color, width },
  });
}

function circle(slide, position, fill, lineColor = "none", name) {
  return box(slide, position, fill, lineColor, "ellipse", name);
}

function footer(slide, number, dark = false) {
  const color = dark ? "#A7C0CD" : "#718691";
  line(slide, { left: 72, top: 674, width: 1136, height: 0 }, dark ? "#2B4A5C" : "#D6DFE2", 1, `footer-rule-${number}`);
  text(slide, "VoiceAI", { left: 72, top: 686, width: 160, height: 20 }, { fontSize: 11, bold: true, color }, `footer-brand-${number}`);
  text(slide, String(number).padStart(2, "0"), { left: 1152, top: 686, width: 56, height: 20 }, { fontSize: 11, color, alignment: "right" }, `footer-page-${number}`);
}

function brandPlaceholder(slide, position, dark = false, name = "brand-placeholder") {
  const fill = dark ? "#11334A" : "#EAF2F1";
  const stroke = dark ? C.teal : "#A8C9C6";
  box(slide, position, fill, stroke, "roundRect", name);
  text(slide, "YOUR BRAND", { left: position.left + 12, top: position.top + 11, width: position.width - 24, height: 20 }, {
    fontSize: 12,
    bold: true,
    color: dark ? C.aqua : C.tealDark,
    alignment: "center",
  }, `${name}-text`);
}

function note(slide, sourceText) {
  slide.speakerNotes.textFrame.setText(sourceText);
}

function sectionTitle(slide, kicker, titleText, subtitle, dark = false) {
  const primary = dark ? C.white : C.ink;
  const secondary = dark ? "#B2C6CF" : C.muted;
  text(slide, kicker.toUpperCase(), { left: 72, top: 54, width: 300, height: 22 }, { fontSize: 11, bold: true, color: dark ? C.teal : C.tealDark }, `kicker-${titleText}`);
  text(slide, titleText, { left: 72, top: 86, width: 1000, height: 64 }, { fontSize: 34, bold: true, color: primary }, `title-${titleText}`);
  text(slide, subtitle, { left: 72, top: 154, width: 870, height: 44 }, { fontSize: 18, color: secondary }, `subtitle-${titleText}`);
}

// Slide 1: cover
{
  const slide = presentation.slides.add();
  slide.background.fill = C.navy;
  const heroBytes = new Uint8Array(await fs.readFile(heroPath));
  slide.images.add({
    blob: heroBytes,
    contentType: "image/png",
    alt: "Abstract teal voice waveform and connected signal paths",
    fit: "cover",
    position: { left: 0, top: 0, width: 1280, height: 720 },
  });
  // A quiet dark scrim on the left keeps the editable title readable over the artwork.
  box(slide, { left: 0, top: 0, width: 650, height: 720 }, "#071827", "none", "rect", "cover-left-scrim");
  brandPlaceholder(slide, { left: 1030, top: 34, width: 178, height: 42 }, true, "cover-brand");
  text(slide, "SALES PRESENTATION", { left: 84, top: 82, width: 260, height: 24 }, { fontSize: 11, bold: true, color: C.teal }, "cover-kicker");
  line(slide, { left: 84, top: 118, width: 56, height: 0 }, C.teal, 3, "cover-accent");
  text(slide, "VoiceAI", { left: 84, top: 164, width: 560, height: 84 }, { fontSize: 58, bold: true, color: C.white }, "cover-title");
  text(slide, "Conversational inbound call handling for service businesses.", { left: 84, top: 274, width: 520, height: 76 }, { fontSize: 27, color: C.aqua }, "cover-subtitle");
  text(slide, "One voice conversation can capture the request, answer questions, and start the next operational step.", { left: 84, top: 382, width: 475, height: 64 }, { fontSize: 18, color: "#B9CBD3" }, "cover-description");
  text(slide, "PRODUCT OVERVIEW", { left: 84, top: 618, width: 250, height: 22 }, { fontSize: 11, bold: true, color: "#A7C0CD" }, "cover-footer-label");
  note(slide, "Source notes: Product positioning and capabilities synthesized from README.md, docs/PRD.md, and docs/RELEASE_NOTE_v0.1.md. Cover artwork generated for this deck and contains no external brand or factual claim.");
}

// Slide 2: business problem
{
  const slide = presentation.slides.add();
  slide.background.fill = C.warm;
  brandPlaceholder(slide, { left: 1030, top: 32, width: 178, height: 42 }, false, "problem-brand");
  sectionTitle(slide, "The business problem", "The phone is where service demand begins", "When staff cannot answer, the work does not wait.");

  const rows = [
    ["MISSED CALLS", "A customer leaves before anyone responds."],
    ["REPETITIVE FRONT-DESK WORK", "Staff re-enter the same details across tools."],
    ["FRAGMENTED FOLLOW-THROUGH", "Bookings, reminders, and handoffs depend on manual coordination."],
  ];
  rows.forEach(([label, body], index) => {
    const y = 246 + index * 102;
    circle(slide, { left: 76, top: y + 4, width: 26, height: 26 }, index === 0 ? C.coral : index === 1 ? C.amber : C.teal, "none", `problem-dot-${index}`);
    text(slide, label, { left: 122, top: y, width: 340, height: 22 }, { fontSize: 12, bold: true, color: C.tealDark }, `problem-label-${index}`);
    text(slide, body, { left: 122, top: y + 26, width: 420, height: 48 }, { fontSize: 20, bold: true, color: C.ink }, `problem-body-${index}`);
    if (index < rows.length - 1) line(slide, { left: 122, top: y + 86, width: 462, height: 0 }, C.line, 1, `problem-rule-${index}`);
  });

  // A simple before / after journey, kept as a flat composition rather than a UI card grid.
  text(slide, "WHEN THE TEAM IS BUSY", { left: 720, top: 238, width: 330, height: 22 }, { fontSize: 12, bold: true, color: C.muted }, "problem-before-label");
  const beforeCall = circle(slide, { left: 720, top: 288, width: 62, height: 62 }, C.paper, C.coral, "problem-before-call");
  text(slide, "CALL", { left: 720, top: 308, width: 62, height: 20 }, { fontSize: 11, bold: true, color: C.ink, alignment: "center" }, "problem-before-call-text");
  const voicemail = box(slide, { left: 846, top: 292, width: 160, height: 54 }, "#FFF8EE", C.amber, "roundRect", "problem-voicemail");
  text(slide, "Voicemail or repeat call", { left: 860, top: 309, width: 132, height: 24 }, { fontSize: 14, bold: true, color: C.ink, alignment: "center" }, "problem-voicemail-text");
  line(slide, { left: 782, top: 319, width: 64, height: 0 }, C.coral, 2, "problem-before-line");
  box(slide, { left: 806, top: 312, width: 24, height: 14 }, C.coral, "none", "rightArrow", "problem-before-arrow");

  text(slide, "WITH VOICEAI", { left: 720, top: 402, width: 330, height: 22 }, { fontSize: 12, bold: true, color: C.tealDark }, "problem-after-label");
  const afterCall = circle(slide, { left: 720, top: 452, width: 62, height: 62 }, "#E8FBF7", C.tealDark, "problem-after-call");
  text(slide, "CALL", { left: 720, top: 472, width: 62, height: 20 }, { fontSize: 11, bold: true, color: C.ink, alignment: "center" }, "problem-after-call-text");
  const conversation = box(slide, { left: 826, top: 456, width: 132, height: 54 }, "#E8FBF7", C.tealDark, "roundRect", "problem-conversation");
  text(slide, "Useful conversation", { left: 838, top: 473, width: 108, height: 24 }, { fontSize: 14, bold: true, color: C.ink, alignment: "center" }, "problem-conversation-text");
  const nextStep = box(slide, { left: 1000, top: 456, width: 178, height: 54 }, C.navy2, C.teal, "roundRect", "problem-next-step");
  text(slide, "Clear next step", { left: 1014, top: 473, width: 150, height: 24 }, { fontSize: 14, bold: true, color: C.white, alignment: "center" }, "problem-next-step-text");
  line(slide, { left: 782, top: 483, width: 44, height: 0 }, C.tealDark, 2, "problem-after-line-1");
  box(slide, { left: 795, top: 476, width: 24, height: 14 }, C.tealDark, "none", "rightArrow", "problem-after-arrow-1");
  line(slide, { left: 958, top: 483, width: 42, height: 0 }, C.tealDark, 2, "problem-after-line-2");
  box(slide, { left: 978, top: 476, width: 24, height: 14 }, C.tealDark, "none", "rightArrow", "problem-after-arrow-2");
  text(slide, "VoiceAI keeps the first conversation useful, even when the team is busy.", { left: 720, top: 558, width: 450, height: 48 }, { fontSize: 18, bold: true, color: C.ink }, "problem-takeaway");
  footer(slide, 2);
  note(slide, "Source notes: Problem framing is a concise synthesis of the problem statement and value proposition in docs/PRD.md. No performance metrics are claimed on this slide.");
}

// Slide 3: workflow
{
  const slide = presentation.slides.add();
  slide.background.fill = C.navy;
  brandPlaceholder(slide, { left: 1030, top: 32, width: 178, height: 42 }, true, "workflow-brand");
  sectionTitle(slide, "The product workflow", "One conversation, several business actions", "VoiceAI routes the request to the right next step while keeping the caller’s context in one place.", true);

  const call = circle(slide, { left: 78, top: 300, width: 112, height: 112 }, C.teal, "none", "workflow-call");
  text(slide, "INBOUND\nCALL", { left: 84, top: 334, width: 100, height: 48 }, { fontSize: 14, bold: true, color: C.navy, alignment: "center" }, "workflow-call-text");
  const router = box(slide, { left: 270, top: 298, width: 190, height: 116 }, C.navy3, C.teal, "roundRect", "workflow-router");
  text(slide, "INTENT ROUTING", { left: 294, top: 322, width: 142, height: 24 }, { fontSize: 15, bold: true, color: C.aqua, alignment: "center" }, "workflow-router-title");
  text(slide, "Caller history + request context", { left: 294, top: 356, width: 142, height: 36 }, { fontSize: 14, color: "#C4D6DD", alignment: "center" }, "workflow-router-body");
  line(slide, { left: 190, top: 356, width: 80, height: 0 }, C.teal, 2, "workflow-call-line");

  const destinations = [
    ["SERVICE INTAKE", "Capture the right details", 548, 224],
    ["APPOINTMENT BOOKING", "Check and reserve a slot", 820, 224],
    ["FAQ ANSWER", "Use the business knowledge base", 548, 432],
    ["CALLBACK OR HANDOFF", "Keep the next action clear", 820, 432],
  ];
  const destinationShapes = [];
  destinations.forEach(([label, body, x, y], index) => {
    const fill = index === 1 ? "#153B56" : "#10283B";
    const stroke = index === 1 ? C.teal : "#31566C";
    const dest = box(slide, { left: x, top: y, width: 230, height: 112 }, fill, stroke, "roundRect", `workflow-destination-${index}`);
    destinationShapes.push(dest);
    circle(slide, { left: x + 18, top: y + 18, width: 14, height: 14 }, index === 1 ? C.amber : C.teal, "none", `workflow-dot-${index}`);
    text(slide, label, { left: x + 46, top: y + 17, width: 166, height: 22 }, { fontSize: 13, bold: true, color: C.aqua }, `workflow-destination-label-${index}`);
    text(slide, body, { left: x + 18, top: y + 52, width: 194, height: 36 }, { fontSize: 15, color: "#C4D6DD" }, `workflow-destination-body-${index}`);
    const lineColor = index === 1 ? C.teal : "#4B7486";
    const routeX = x < 700 ? 500 : 790;
    const routerY = 356;
    const destinationY = y + 56;
    line(slide, { left: 460, top: routerY, width: routeX - 460, height: 0 }, lineColor, 2, `workflow-route-horizontal-${index}`);
    line(slide, { left: routeX, top: Math.min(routerY, destinationY), width: 0, height: Math.abs(destinationY - routerY) }, lineColor, 2, `workflow-route-vertical-${index}`);
    line(slide, { left: routeX, top: destinationY, width: x - routeX, height: 0 }, lineColor, 2, `workflow-route-destination-${index}`);
  });

  text(slide, "Structured records and summaries give staff a clear handoff when the call continues beyond automation.", { left: 270, top: 590, width: 700, height: 34 }, { fontSize: 16, color: "#B5C9D2" }, "workflow-bottom-note");
  footer(slide, 3, true);
  note(slide, "Source notes: Workflow based on serviceBot/graph/state.py, serviceBot/graph/routing.py, serviceBot/graph/nodes.py, and the capabilities documented in README.md and docs/RELEASE_NOTE_v0.1.md.");
}

// Slide 4: connected operations
{
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  brandPlaceholder(slide, { left: 1030, top: 32, width: 178, height: 42 }, false, "operations-brand");
  sectionTitle(slide, "Connected operations", "The call connects to the operation", "VoiceAI turns a conversation into updates the team can act on.");

  const center = circle(slide, { left: 546, top: 276, width: 184, height: 184 }, C.navy2, C.teal, "operations-center");
  text(slide, "VoiceAI", { left: 572, top: 332, width: 132, height: 36 }, { fontSize: 28, bold: true, color: C.white, alignment: "center" }, "operations-center-title");
  text(slide, "conversation\n→ action", { left: 576, top: 378, width: 124, height: 44 }, { fontSize: 16, color: C.aqua, alignment: "center" }, "operations-center-body");
  const nodes = [
    ["CUSTOMER RECORDS", "History, vehicle details, active requests", 102, 250, C.coral],
    ["GOOGLE CALENDAR", "Availability and booked slots", 894, 250, C.teal],
    ["KNOWLEDGE BASE", "Business answers grounded in source material", 102, 474, C.amber],
    ["EMAIL + SMS", "Customer and staff notifications", 894, 474, C.teal],
  ];
  nodes.forEach(([label, body, x, y, accent], index) => {
    const node = box(slide, { left: x, top: y, width: 278, height: 92 }, "#F3F8F7", "#C9DEDA", "roundRect", `operations-node-${index}`);
    circle(slide, { left: x + 18, top: y + 20, width: 16, height: 16 }, accent, "none", `operations-dot-${index}`);
    text(slide, label, { left: x + 48, top: y + 18, width: 206, height: 22 }, { fontSize: 13, bold: true, color: C.tealDark }, `operations-label-${index}`);
    text(slide, body, { left: x + 18, top: y + 48, width: 238, height: 30 }, { fontSize: 14, color: C.muted }, `operations-body-${index}`);
    slide.shapes.connect(center, node, { kind: "elbow", fromSide: x < 500 ? "left" : "right", toSide: x < 500 ? "right" : "left", line: { style: "solid", fill: "#8EB5B1", width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  });

  const portal = box(slide, { left: 102, top: 604, width: 1076, height: 44 }, C.navy2, "none", "roundRect", "operations-portal-band");
  text(slide, "STAFF PORTAL", { left: 122, top: 616, width: 130, height: 20 }, { fontSize: 12, bold: true, color: C.teal }, "operations-portal-title");
  text(slide, "Transcripts", { left: 306, top: 616, width: 120, height: 20 }, { fontSize: 13, bold: true, color: C.white }, "operations-portal-transcripts");
  text(slide, "Service catalog", { left: 480, top: 616, width: 140, height: 20 }, { fontSize: 13, bold: true, color: C.white }, "operations-portal-catalog");
  text(slide, "Calendar controls", { left: 674, top: 616, width: 150, height: 20 }, { fontSize: 13, bold: true, color: C.white }, "operations-portal-calendar");
  text(slide, "Escalation visibility", { left: 870, top: 616, width: 180, height: 20 }, { fontSize: 13, bold: true, color: C.white }, "operations-portal-escalation");
  footer(slide, 4);
  note(slide, "Source notes: Integrations and portal capabilities based on serviceBot/services/calendar_availability.py, serviceBot/services/google_calendar.py, serviceBot/services/rag.py, serviceBot/services/gmail.py, serviceBot/services/twilio_sms.py, serviceBot/static/index.html, and docs/RELEASE_NOTE_v0.1.md.");
}

// Slide 5: sales close
{
  const slide = presentation.slides.add();
  slide.background.fill = C.navy;
  brandPlaceholder(slide, { left: 1030, top: 32, width: 178, height: 42 }, true, "close-brand");
  sectionTitle(slide, "A practical starting point", "Start with one high-volume call flow", "A focused pilot lets the team map the conversation, the systems it touches, and the next operational step.", true);

  text(slide, "AUTO-SERVICE EXAMPLE", { left: 72, top: 250, width: 260, height: 22 }, { fontSize: 12, bold: true, color: C.teal }, "close-example-kicker");
  text(slide, "A brake-repair call becomes a captured service request, a viable appointment slot, and a clear staff follow-up.", { left: 72, top: 284, width: 540, height: 96 }, { fontSize: 27, bold: true, color: C.white }, "close-example-body");
  line(slide, { left: 72, top: 410, width: 540, height: 0 }, "#2B4A5C", 1, "close-rule");
  text(slide, "Pilot scope", { left: 72, top: 438, width: 130, height: 22 }, { fontSize: 12, bold: true, color: "#A7C0CD" }, "close-pilot-label");
  text(slide, "Configure the service catalog\nConnect calendars and notifications\nReview transcripts and exceptions", { left: 72, top: 470, width: 460, height: 92 }, { fontSize: 18, color: "#C7D8DE" }, "close-pilot-list");
  text(slide, "Use the first pilot to map one workflow and the systems it touches.", { left: 72, top: 604, width: 500, height: 30 }, { fontSize: 16, bold: true, color: C.aqua }, "close-next-step");

  // A lightweight editable portal preview with labels only, avoiding invented data.
  box(slide, { left: 732, top: 242, width: 438, height: 328 }, "#102C41", "#31566C", "roundRect", "close-portal-frame");
  text(slide, "STAFF PORTAL", { left: 760, top: 268, width: 180, height: 24 }, { fontSize: 14, bold: true, color: C.teal }, "close-portal-title");
  line(slide, { left: 760, top: 310, width: 380, height: 0 }, "#31566C", 1, "close-portal-rule");
  const portalRows = [
    ["Service catalog", "Edit offers and intake fields", C.teal],
    ["Calendar controls", "Manage availability and bookings", C.amber],
    ["Transcript review", "See summaries and full call context", C.aqua],
    ["Escalation queue", "Surface exceptions for staff", C.coral],
  ];
  portalRows.forEach(([label, body, accent], index) => {
    const y = 336 + index * 52;
    circle(slide, { left: 760, top: y + 2, width: 12, height: 12 }, accent, "none", `close-portal-dot-${index}`);
    text(slide, label, { left: 792, top: y - 2, width: 150, height: 20 }, { fontSize: 14, bold: true, color: C.white }, `close-portal-row-label-${index}`);
    text(slide, body, { left: 954, top: y - 2, width: 190, height: 20 }, { fontSize: 13, color: "#B3C9D2" }, `close-portal-row-body-${index}`);
    if (index < portalRows.length - 1) line(slide, { left: 760, top: y + 34, width: 380, height: 0 }, "#29495D", 1, `close-portal-row-rule-${index}`);
  });
  text(slide, "CONTACT / DEMO", { left: 1010, top: 604, width: 198, height: 28 }, { fontSize: 12, bold: true, color: C.teal, alignment: "right" }, "close-contact-placeholder");
  footer(slide, 5, true);
  note(slide, "Source notes: Closing workflow and portal capabilities based on docs/PRD.md, README.md, serviceBot/static/index.html, and docs/RELEASE_NOTE_v0.1.md. Copy intentionally avoids unsupported ROI or performance claims.");
}

const candidatePath = path.join(stagingDir, "candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const requirements = {
  explicitTotalSlideCount: 5,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
};

const finalResult = await finalizePresentation({
  ...requirements,
  workspaceDir,
  candidatePath,
  finalPath: outputPath,
  pythonExecutable: "/Users/rohanroy/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3",
  integrityValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
  ],
  requiredNativeTableOwnerSlides: [],
  fontPolicy: { basis: "design", families: [fontFamily] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "VoiceAI_sales_enablement_v4.validation.json"),
});

for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const slide = presentation.slides.items[index];
  const preview = await presentation.export({ slide, format: "png", scale: 1.5 });
  await fs.writeFile(path.join(buildDir, `slide-${index + 1}.png`), new Uint8Array(await preview.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(buildDir, `slide-${index + 1}.layout.json`), await layout.text());
}
const montage = await presentation.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(buildDir, "montage.webp"), new Uint8Array(await montage.arrayBuffer()));
await fs.writeFile(path.join(buildDir, "inspect.ndjson"), JSON.stringify(await presentation.inspect({ kind: "slide,textbox,shape,image,table,chart,notes,layout", maxChars: 20000 }), null, 2));

console.log(JSON.stringify({ outputPath, fontFamily, slideCount: presentation.slides.items.length, finalResult }, null, 2));
