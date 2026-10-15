import { desktopCapturer, screen } from "electron";
import type { CapturedScreenshot } from "@shared/deviceTypes";

/**
 * Captures the primary display only — not every connected monitor. This
 * mirrors the backend's "one screenshot per request" contract (see
 * POST /devices/{id}/screenshot/request's docstring: "ONE screenshot...
 * no continuous recording/live-streaming mode"); capturing every monitor
 * on a multi-display setup would multiply the privacy footprint of a
 * single admin request without that request having asked for it.
 *
 * Must run in the main process — desktopCapturer is not available to a
 * renderer with nodeIntegration: false (see main/index.ts webPreferences),
 * same constraint as hardwareInfo.ts.
 */
export async function captureScreenshot(): Promise<CapturedScreenshot> {
  const primaryDisplay = screen.getPrimaryDisplay();
  // scaleFactor so the capture is full native resolution on HiDPI
  // displays, not a blurry 1x-scaled thumbnail.
  const { width, height } = primaryDisplay.size;
  const scaleFactor = primaryDisplay.scaleFactor || 1;

  const sources = await desktopCapturer.getSources({
    types: ["screen"],
    thumbnailSize: { width: Math.round(width * scaleFactor), height: Math.round(height * scaleFactor) },
  });

  // display_id match when available (multi-monitor correctness); falls
  // back to the first source for the common single-display case where
  // display_id isn't populated on every platform.
  const source =
    sources.find((s) => s.display_id === String(primaryDisplay.id)) ?? sources[0];
  if (!source) {
    throw new Error("No screen source available to capture");
  }

  const image = source.thumbnail;
  const size = image.getSize();
  return {
    base64Png: image.toPNG().toString("base64"),
    width: size.width,
    height: size.height,
  };
}
