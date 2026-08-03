/**
 * Interactive site poll — no signup.
 * - Device/browser fingerprint (canvas + UA + screen + tz + hardware)
 * - Once per calendar day (Asia/Jerusalem) per fingerprint
 * - Tallies via free CounterAPI (CORS open) + local mirror
 */
(function (global) {
  const NS = "election-meter-il-v1";
  const API = "https://api.counterapi.dev/v1";
  const TZ = "Asia/Jerusalem";
  const LS_FP = "em_fp_v1";
  const LS_VOTE = "em_vote_v1"; // { day, party, fp, at }
  const LS_MIRROR = "em_tallies_v1";

  function todayKey() {
    try {
      return new Intl.DateTimeFormat("en-CA", {
        timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit"
      }).format(new Date());
    } catch {
      return new Date().toISOString().slice(0, 10);
    }
  }

  function partyKey(name) {
    return String(name || "other")
      .replace(/[^a-zA-Z0-9\u0590-\u05FF]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 48) || "other";
  }

  async function sha256(text) {
    const data = new TextEncoder().encode(text);
    const buf = await crypto.subtle.digest("SHA-256", data);
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  function canvasSignal() {
    try {
      const c = document.createElement("canvas");
      c.width = 240; c.height = 60;
      const ctx = c.getContext("2d");
      ctx.textBaseline = "top";
      ctx.font = "14px 'Heebo', Arial";
      ctx.fillStyle = "#f60";
      ctx.fillRect(10, 8, 100, 30);
      ctx.fillStyle = "#069";
      ctx.fillText("מד-בחירות·fp", 12, 12);
      ctx.strokeStyle = "#ff0";
      ctx.beginPath();
      ctx.arc(180, 30, 18, 0, Math.PI * 2);
      ctx.stroke();
      return c.toDataURL();
    } catch {
      return "no-canvas";
    }
  }

  async function buildFingerprint() {
    const n = navigator;
    const s = screen;
    const parts = [
      n.userAgent || "",
      n.language || "",
      (n.languages || []).join(","),
      n.platform || "",
      n.hardwareConcurrency || "",
      n.deviceMemory || "",
      n.maxTouchPoints || "",
      s.width + "x" + s.height + "x" + s.colorDepth,
      s.availWidth + "x" + s.availHeight,
      Intl.DateTimeFormat().resolvedOptions().timeZone || "",
      new Date().getTimezoneOffset(),
      canvasSignal(),
      n.webdriver ? "wd1" : "wd0",
    ];
    // stable per browser profile
    let cached = localStorage.getItem(LS_FP);
    if (cached && cached.length === 64) return cached;
    const hash = await sha256(parts.join("|"));
    localStorage.setItem(LS_FP, hash);
    return hash;
  }

  function readLocalVote() {
    try {
      const raw = localStorage.getItem(LS_VOTE);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function hasVotedToday(fp) {
    const v = readLocalVote();
    if (!v) return false;
    return v.day === todayKey() && v.fp === fp;
  }

  async function apiGet(key) {
    const url = `${API}/${NS}/${encodeURIComponent(key)}/`;
    const r = await fetch(url, { method: "GET", mode: "cors", cache: "no-store" });
    if (r.status === 404) return 0;
    if (!r.ok) throw new Error("get " + r.status);
    const j = await r.json();
    return Number(j.count || j.value || 0);
  }

  async function apiUp(key) {
    // try /up/ then /up
    const urls = [
      `${API}/${NS}/${encodeURIComponent(key)}/up/`,
      `${API}/${NS}/${encodeURIComponent(key)}/up`,
    ];
    let lastErr;
    for (const url of urls) {
      try {
        const r = await fetch(url, { method: "GET", mode: "cors", cache: "no-store" });
        if (!r.ok && r.status !== 301 && r.status !== 302) {
          lastErr = new Error("up " + r.status);
          continue;
        }
        const j = await r.json();
        return Number(j.count || j.value || 0);
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error("up failed");
  }

  function mirrorGet() {
    try {
      return JSON.parse(localStorage.getItem(LS_MIRROR) || "{}");
    } catch {
      return {};
    }
  }

  function mirrorSet(party, n) {
    const m = mirrorGet();
    m[party] = n;
    m._total = Object.keys(m)
      .filter((k) => !k.startsWith("_"))
      .reduce((a, k) => a + (Number(m[k]) || 0), 0);
    m._updated = new Date().toISOString();
    localStorage.setItem(LS_MIRROR, JSON.stringify(m));
    return m;
  }

  async function fetchTallies(parties) {
    const out = {};
    let total = 0;
    const mirror = mirrorGet();
    await Promise.all(
      parties.map(async (p) => {
        const key = partyKey(p);
        try {
          const n = await apiGet(key);
          out[p] = n;
          total += n;
          mirrorSet(p, n);
        } catch {
          out[p] = Number(mirror[p] || 0);
          total += out[p];
        }
      })
    );
    // total counter (best-effort)
    try {
      out.__total = await apiGet("total-votes");
    } catch {
      out.__total = total;
    }
    return out;
  }

  async function castVote(party) {
    const fp = await buildFingerprint();
    const day = todayKey();
    if (hasVotedToday(fp)) {
      const prev = readLocalVote();
      return { ok: false, reason: "already", vote: prev, tallies: null };
    }
    // write lock first (optimistic anti double-click)
    const record = { day, party, fp, at: new Date().toISOString() };
    localStorage.setItem(LS_VOTE, JSON.stringify(record));
    sessionStorage.setItem(LS_VOTE, JSON.stringify(record));

    let remote = 0;
    let total = 0;
    try {
      remote = await apiUp(partyKey(party));
      try { total = await apiUp("total-votes"); } catch { total = remote; }
      mirrorSet(party, remote);
    } catch (e) {
      // keep local lock; mirror increment locally
      const m = mirrorGet();
      remote = Number(m[party] || 0) + 1;
      mirrorSet(party, remote);
      console.warn("remote tally failed, local mirror only", e);
    }
    return { ok: true, vote: record, remote, total };
  }

  function resetLocalForDebug() {
    localStorage.removeItem(LS_VOTE);
    sessionStorage.removeItem(LS_VOTE);
  }

  global.ElectionVote = {
    todayKey,
    partyKey,
    buildFingerprint,
    hasVotedToday,
    readLocalVote,
    fetchTallies,
    castVote,
    mirrorGet,
    resetLocalForDebug,
  };
})(window);
