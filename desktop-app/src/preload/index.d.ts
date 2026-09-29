import type { EwmpBridge } from "./index";

declare global {
  interface Window {
    ewmp: EwmpBridge;
  }
}
