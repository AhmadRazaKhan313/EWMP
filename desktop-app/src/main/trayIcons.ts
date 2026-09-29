import { nativeImage, type NativeImage } from "electron";
import type { TrayIconStatus } from "@shared/deviceTypes";

/**
 * Small filled-dot tray icons, one per timer status. Generated offline
 * (see tools/generate-tray-icons.py in the repo history) rather than
 * shipped as separate asset files — three ~16x16 PNGs are small enough
 * to inline, and it avoids adding an icon build step for three dots.
 * @2x (32px) representations are added for HiDPI/Retina displays.
 *
 * idle      — gray  (#9CA3AF): not checked in
 * active    — green (#22C55E): checked in, working
 * on_break  — amber (#F59E0B): checked in, on a break
 */

const IDLE_16 =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAcUlEQVR4nGNgoBAw4pL4////fxSFjIxY1bLg0jh3yQas4ugGMaIrQteIDpJjAlAMYSJFM8xlyN5jwqeYGMBEiu3YXEEdFwy8AYyMjIzJMQFEa0KOSup5gVhXoCckjPSNKynDDMeblLEZhOxCgs4jBwAALaI8CBSFyLgAAAAASUVORK5CYII=";
const IDLE_32 =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAxklEQVR4nO2XMRLDIAwET5k80A9wl3elywPyQ7nI4LExCCmDsAquNeiWM8UB3CyybmBmFgcSmWY+rcbvz1e1TgvSXKQ1zvVaF2hAxI/MzFbjEogE8fA0B37JSfemCNDLXANxAeht3oI4AXiZSxDVOzBKO4D36ZPyFGIkMOr0SccUYiQwASbABCAiSgVihI4dIUYCwLgU8oYUJwHAP4VSP7wk4AVRK6fFX9AbQmrG1TvQC6JVy2M/TP4B0RqbAXKQ6kDj4/R2bX/WgiZ0CTJDAAAAAElFTkSuQmCC";
const ACTIVE_16 =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAcUlEQVR4nGNgoBAw4pL4////fxSFjIxY1bLg0qh8LB6rOLpBjOiK0DWig7tWC1EMYSJFM8xlyN5jwqeYGMBEiu3YXEEdFwy8AYyMjIx3rRYSrQk5KqnnBWJdgZ6QMNI3rqQMMxxvUsZmELILCTqPHAAAv/Q7X/6MXv8AAAAASUVORK5CYII=";
const ACTIVE_32 =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAx0lEQVR4nO2XwRHDIAwET5l04i7cTGpLM+kitciPDB4bg5AyCOvBfQ265czjAG4WWTcwM4sDiUwzn1bj5fNSrdOCNBdpjXN91zc0IOJHZmarcQlEgnh4mgO/5KR7UwToZa6BuAD0Nm9BnAC8zCWI6h0YpR3A+/RJeQoxEhh1+qRjCjESmAATYAIQEaUCMULHjhAjAWBcCnlDipMA4J9CqR9eEvCCqJXT4i/oDSE14+od6AXRquWxHyb/gGiNzQA5SHWg8XF6uzZEC4F9ALoM9AAAAABJRU5ErkJggg==";
const ON_BREAK_16 =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAb0lEQVR4nMVSQQ7AIAizZCezT/qyfdLsyk4myMDhZrIepS0lNqWPgDdgZu6IgMndPOF57Oa7NoImaaFGLrUzoRlxSybPoxE5AprZbqVYk+B/AwDIpYZF8ivXnRBNoYt067dX5WY+rLJlJBM+xnuDCyOyO7jnS1Y5AAAAAElFTkSuQmCC";
const ON_BREAK_32 =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAxElEQVR4nO2XsQ7DIAxEz1WnKD/ZL+tPVl2doSJKCBi7wsQDtwZ8jwvDAdwssm5gZhYHEplmPq3G3/eqWqcFaS7SGudaXh9oQMSPzMxW4xKIBPHwNAd+yUn3pgjQy1wDcQHobd6COAF4mUsQ1TswSjuA9+mT8hRiJDDq9EnHFGIkMAEmwAQgIkoFYoSOHSFGAsC4FPKGFCcBwD+FUj+8JOAFUSunxV/QG0JqxtU70AuiVctjP0z+AdEamwFykOpA4+P0dm1dBoHWHvGJzgAAAABJRU5ErkJggg==";

function buildIcon(png16: string, png32: string): NativeImage {
  const icon = nativeImage.createFromDataURL(png16);
  icon.addRepresentation({ scaleFactor: 2, dataURL: png32 });
  return icon;
}

const ICONS: Record<TrayIconStatus, NativeImage> = {
  idle: buildIcon(IDLE_16, IDLE_32),
  active: buildIcon(ACTIVE_16, ACTIVE_32),
  on_break: buildIcon(ON_BREAK_16, ON_BREAK_32),
};

export function getTrayIcon(status: TrayIconStatus): NativeImage {
  return ICONS[status];
}
