import Store from "electron-store";

/**
 * Encrypted on-disk store for auth tokens and small pieces of local state.
 *
 * This module is imported ONLY by the main process. The renderer never
 * gets a reference to it directly — see src/preload/index.ts, which
 * exposes a narrow `window.ewmp.secureStore` bridge over IPC instead.
 * That's the whole point of `contextIsolation: true` +
 * `nodeIntegration: false`: even if a compromised/malicious script somehow
 * ran in the renderer, it can only call the specific IPC channels this app
 * chose to expose, not read arbitrary files or Node modules.
 *
 * `electron-store`'s `encryptionKey` obscures the file on disk from casual
 * inspection (a plain text editor won't show tokens) — it is NOT a secret
 * held elsewhere or tied to OS keychain/DPAPI, so treat this as
 * "obfuscated at rest," not "cryptographically secure against a
 * determined local attacker with code execution as this user." Revisit
 * with `keytar`/OS credential-manager integration if that threat model
 * matters for this deployment.
 */
interface SecureStoreSchema {
  accessToken?: string;
  refreshToken?: string;
  tenantId?: string;
  serverUrl?: string;
  // Phase 4 item #1 (self-enrollment). deviceConsentAcknowledged is
  // stored the moment the employee clicks through ConsentNotice — kept
  // separate from deviceId/agentToken so a transient enrollment failure
  // (e.g. network blip) never causes the notice to be shown again; only
  // an explicit logout/reset should ever re-ask for consent.
  deviceConsentAcknowledged?: string;
  deviceId?: string;
  agentToken?: string;
}

const store = new Store<SecureStoreSchema>({
  name: "ewmp-secure",
  // A fixed key still raises the bar above plaintext, but anyone reading
  // this open-source app's source has the key too — see the caveat above.
  encryptionKey: "ewmp-desktop-local-store-v1",
  clearInvalidConfig: true,
});

export type SecureStoreKey = keyof SecureStoreSchema;

export function getSecureValue<K extends SecureStoreKey>(key: K): SecureStoreSchema[K] | null {
  return store.get(key) ?? null;
}

export function setSecureValue<K extends SecureStoreKey>(key: K, value: SecureStoreSchema[K]): void {
  store.set(key, value);
}

export function deleteSecureValue(key: SecureStoreKey): void {
  store.delete(key);
}

export function clearSecureStore(): void {
  store.clear();
}
