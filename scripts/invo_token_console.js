/*
 * Invo refresh-token extractor (best effort, runs entirely in your browser)
 * =========================================================================
 * Usage
 *   1. Open https://app.invoapp.com and make sure you are logged in.
 *   2. DevTools -> Console.
 *   3. Paste this whole file, press Enter.
 *
 * What it does
 *   Flutter stores the refresh token in localStorage under
 *   "FlutterSecureStorage.REFRESH_TOKEN" as an AES-encrypted blob, with the
 *   AES key kept alongside it. This script enumerates localStorage, treats
 *   every short base64 value as a key candidate, tries AES-GCM and AES-CBC
 *   against every candidate blob, and accepts only output that parses as a
 *   three-part JWT. The token never leaves the page: it is printed locally
 *   and copied to your clipboard.
 *
 *   If decryption fails it dumps every localStorage key/value so you can
 *   fall back to manual inspection. Nothing is uploaded anywhere.
 *
 * Then:
 *   .venv\Scripts\python.exe src\integrations\invo_ctrader_copier.py --set-token "<paste>"
 * which validates the JWT against the live API and writes it to .env.
 */
(async () => {
  const b64ToBytes = (s) => {
    const norm = s.replace(/-/g, "+").replace(/_/g, "/").replace(/=+$/, "");
    const bin = atob(norm + "=".repeat((4 - (norm.length % 4)) % 4));
    return Uint8Array.from(bin, (c) => c.charCodeAt(0));
  };
  const bytesToStr = (b) => new TextDecoder().decode(b);
  const isJwt = (s) => typeof s === "string" && /^eyJ[\w-]+\.[\w-]+\.[\w-]*$/.test(s.trim());
  const looksB64 = (s) => typeof s === "string" && /^[A-Za-z0-9+/=_-]{20,}$/.test(s.trim());

  const entries = Object.entries(localStorage);
  console.log(`[invo] ${entries.length} localStorage entries`);

  // --- candidate keys: short blobs decoding to 16/24/32 bytes --------------
  const keys = [];
  const pushKey = (raw, origin) => {
    try {
      const bytes = b64ToBytes(raw);
      if ([16, 24, 32].includes(bytes.length)) keys.push({ bytes, origin });
    } catch (_) {}
  };
  for (const [k, v] of entries) {
    if (looksB64(v)) pushKey(v, k);
    try {
      const parsed = JSON.parse(v);
      for (const val of Object.values(parsed)) {
        if (typeof val === "string" && looksB64(val)) pushKey(val, `${k}.json`);
      }
    } catch (_) {}
  }
  console.log(`[invo] ${keys.length} AES key candidate(s)`);

  // --- candidate ciphertexts: anything with an iv + payload ---------------
  const blobs = [];
  const addBlob = (iv, data, origin) => {
    if (!iv || !data) return;
    try {
      blobs.push({ iv: b64ToBytes(iv), data: b64ToBytes(data), origin });
    } catch (_) {}
  };
  for (const [k, v] of entries) {
    if (k.startsWith("FlutterSecureStorage")) {
      try {
        const p = JSON.parse(v);
        addBlob(p.iv || p.IV, p.value || p.ciphertext || p.data || p.ct, k);
      } catch (_) {
        const parts = v.split(":");
        if (parts.length === 2) addBlob(parts[0], parts[1], k);
      }
    }
  }
  console.log(`[invo] ${blobs.length} encrypted blob candidate(s)`);

  const attempts = [];
  const tryDecrypt = async (keyBytes, blob, algo) => {
    const ivLen = algo === "AES-GCM" ? 12 : 16;
    const iv = blob.iv.length === ivLen ? blob.iv : blob.iv.subarray(0, ivLen);
    try {
      const key = await crypto.subtle.importKey("raw", keyBytes, { name: algo }, false, ["decrypt"]);
      const params = algo === "AES-GCM"
        ? { name: "AES-GCM", iv, tagLength: 128 }
        : { name: "AES-CBC", iv };
      const plain = await crypto.subtle.decrypt(params, key, blob.data);
      return bytesToStr(plain).replace(/\0+$/, "");
    } catch (_) {
      return null;
    }
  };

  for (const blob of blobs) {
    for (const key of keys) {
      for (const algo of ["AES-GCM", "AES-CBC"]) {
        const out = await tryDecrypt(key.bytes, blob, algo);
        if (!out) continue;
        attempts.push({ origin: blob.origin, algo, sample: out.slice(0, 40) });
        const candidate = out.replace(/^"|"$/g, "").trim();
        if (isJwt(candidate)) {
          console.log(`[invo] MATCH via ${algo} on ${blob.origin}`);
          console.log(candidate);
          try {
            await navigator.clipboard.writeText(candidate);
            console.log("[invo] copied to clipboard");
          } catch (_) {
            console.log("[invo] clipboard blocked - copy the line above manually");
          }
          return;
        }
      }
    }
  }

  console.warn("[invo] no JWT recovered automatically.");
  if (attempts.length) {
    console.warn("[invo] partial decrypts (inspect these):", attempts);
  }
  console.table(
    entries.map(([k, v]) => ({
      key: k,
      value: v.length > 120 ? v.slice(0, 120) + "..." : v,
    }))
  );
  console.warn("[invo] fallback: look for the FlutterSecureStorage.* entry holding");
  console.warn("        {\"iv\":...,\"value\":...} and its sibling base64 AES key.");
})();
