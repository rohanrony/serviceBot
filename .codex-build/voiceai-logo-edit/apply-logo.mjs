import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "/Users/rohanroy/Coding/voiceService";
const skillDir = "/Users/rohanroy/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const buildDir = path.join(workspaceDir, ".codex-build", "voiceai-logo-edit");
const stagingDir = path.join(buildDir, ".codex-finalizer");
const sourcePath = path.join(workspaceDir, ".codex-output", "VoiceAI_sales_enablement_v4.pptx");
const outputPath = path.join(workspaceDir, ".codex-output", "VoiceAI_sales_enablement_edvenswa.pptx");
const logoPath = path.join(buildDir, "edvenswa-logo.png");

const { finalizePresentation } = await import(pathToFileURL(
  path.join(skillDir, "container_tools/artifact_tool_utils.mjs"),
).href);

await fs.mkdir(buildDir, { recursive: true });
await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(outputPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const logoBytes = new Uint8Array(await fs.readFile(logoPath));

function inspectText(snapshot) {
  return typeof snapshot?.ndjson === "string" ? snapshot.ndjson : JSON.stringify(snapshot, null, 2);
}

const before = await presentation.inspect({
  kind: "slide,textbox,shape,image,table,chart,notes,layout",
  search: "YOUR BRAND",
  maxChars: 12000,
});
await fs.writeFile(path.join(buildDir, "before-brand-inspect.ndjson"), inspectText(before));

for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const slide = presentation.slides.items[index];
  const previewBefore = await slide.export({ format: "png", scale: 1.5 });
  await fs.writeFile(path.join(buildDir, `before-slide-${index + 1}.png`), new Uint8Array(await previewBefore.arrayBuffer()));
  const layoutBefore = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(buildDir, `before-slide-${index + 1}.layout.json`), await layoutBefore.text());
}
const montageBefore = await presentation.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(buildDir, "before-montage.webp"), new Uint8Array(await montageBefore.arrayBuffer()));

for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const slide = presentation.slides.items[index];
  const panel = slide.shapes.add({
    geometry: "roundRect",
    name: `edvenswa-logo-panel-${index + 1}`,
    position: { left: 1026, top: 18, width: 186, height: 120 },
    fill: "#FFFFFF",
    line: { style: "solid", fill: "#5FE1D2", width: 1 },
    borderRadius: "rounded-xl",
  });
  panel.text = "";
  slide.images.add({
    blob: logoBytes,
    contentType: "image/png",
    alt: "Edvenswa logo",
    fit: "contain",
    position: { left: 1058, top: 23, width: 122, height: 110 },
    name: `edvenswa-logo-${index + 1}`,
  });
}

const after = await presentation.inspect({
  kind: "slide,textbox,shape,image,table,chart,notes,layout",
  search: "Edvenswa",
  maxChars: 12000,
});
await fs.writeFile(path.join(buildDir, "after-brand-inspect.ndjson"), inspectText(after));

for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const slide = presentation.slides.items[index];
  const previewAfter = await slide.export({ format: "png", scale: 1.5 });
  await fs.writeFile(path.join(buildDir, `after-slide-${index + 1}.png`), new Uint8Array(await previewAfter.arrayBuffer()));
  const layoutAfter = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(buildDir, `after-slide-${index + 1}.layout.json`), await layoutAfter.text());
}
const montageAfter = await presentation.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(buildDir, "after-montage.webp"), new Uint8Array(await montageAfter.arrayBuffer()));

const candidatePath = path.join(stagingDir, "candidate-edvenswa.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const finalResult = await finalizePresentation({
  explicitTotalSlideCount: 5,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
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
  fontPolicy: { basis: "design", families: ["Helvetica Neue"] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "VoiceAI_sales_enablement_edvenswa.validation.json"),
});

console.log(JSON.stringify({ outputPath, slideCount: presentation.slides.items.length, finalResult }, null, 2));
