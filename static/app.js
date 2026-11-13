/* SPHEREx Flipbook frontend */
(() => {
  const $ = (id) => document.getElementById(id);
  let frames = [];
  let imgs = [];
  let idx = 0;
  let timer = null;
  let playing = true;
  let aladin = null;
  let gaiaCat = null;
  let source = "unknown";

  const params = () => {
    const q = new URLSearchParams({
      ra: $("ra").value,
      dec: $("dec").value,
      fov: $("fov").value,
      band: $("band").value,
      mode: $("mode").value,
      speed: $("speed").value,
      a: (Number($("stretch").value) / 100).toFixed(2),
      gaia: $("gaia").checked ? "1" : "0",
      diff: $("diffMode").checked ? "1" : "0",
    });
    return q;
  };

  const qs = () => params().toString();

  function setBadge(src, warning) {
    source = src;
    const el = $("sourceBadge");
    el.className = "badge " + (src === "real" ? "real" : "fake");
    el.textContent =
      src === "real"
        ? "REAL IRSA / SPHEREx"
        : warning || "FAKE placeholders — not SPHEREx data";
  }

  function flashLoop() {
    const panel = $("blinkPanel");
    panel.classList.add("flash");
    setTimeout(() => panel.classList.remove("flash"), 220);
  }

  function updateLegend() {
    // WiseView-style +, -, . when diff mode uses first as +, second as -, rest .
    if (!$("diffMode").checked || frames.length < 2) {
      $("legend").textContent = frames.map((_, i) => (i === idx ? "*" : ".")).join("");
      return;
    }
    $("legend").textContent = frames
      .map((_, i) => {
        if (i === 0) return "+";
        if (i === 1) return "-";
        return ".";
      })
      .join("");
  }

  function showFrame() {
    if (!imgs.length) return;
    if ($("diffMode").checked && frames.length >= 2) {
      const a = frames[0].id;
      const b = frames[Math.min(1, frames.length - 1)].id;
      $("view").src = `/api/diff?id_a=${encodeURIComponent(a)}&id_b=${encodeURIComponent(b)}&${qs()}`;
      $("info").textContent = `diff ${a} − ${b}`;
    } else {
      $("view").src = imgs[idx].src;
      const fr = frames[idx];
      $("info").textContent = `frame ${idx + 1}/${frames.length} · MJD ${Number(fr.mjd).toFixed(3)} · ${fr.band}`;
    }
    updateLegend();
  }

  function play() {
    clearInterval(timer);
    if (!playing || !imgs.length || $("diffMode").checked) return;
    timer = setInterval(() => {
      const next = (idx + 1) % imgs.length;
      if (next === 0) flashLoop();
      idx = next;
      showFrame();
    }, Number($("speed").value));
  }

  async function loadMeta(obsId) {
    try {
      const m = await (await fetch(`/api/meta/${encodeURIComponent(obsId)}?${qs()}`)).json();
      const bits = [];
      if (m.n_bands) bits.push(`${m.n_bands} bands`);
      if (m.has_flags) bits.push(`flags${m.flagged_pixels != null ? ` (${m.flagged_pixels} px)` : ""}`);
      if (m.aligned) bits.push("aligned");
      if (m.align_fallback) bits.push("align≈cutout");
      if (m.spectrum && m.spectrum.length) {
        const finite = m.spectrum.filter((v) => Number.isFinite(v));
        if (finite.length) bits.push(`spectrum n=${finite.length}`);
      }
      $("meta").textContent = bits.join(" · ");
    } catch {
      $("meta").textContent = "";
    }
  }

  function gotoAladin() {
    if (!aladin) return;
    const ra = Number($("ra").value);
    const dec = Number($("dec").value);
    const fov = Number($("fov").value);
    aladin.gotoRaDec(ra, dec);
    aladin.setFov(Math.max(fov * 3, 0.2));
  }

  async function toggleGaia() {
    if (!aladin) return;
    if (!$("gaia").checked) {
      if (gaiaCat) {
        aladin.removeCatalog(gaiaCat);
        gaiaCat = null;
      }
      return;
    }
    const ra = Number($("ra").value);
    const dec = Number($("dec").value);
    const radius = Math.max(Number($("fov").value), 0.05);
    try {
      gaiaCat = await A.catalogFromVizieR(
        "I/355/gaiadr3",
        `${ra} ${dec}`,
        radius,
        { onClick: "showTable", name: "Gaia DR3" }
      );
      aladin.addCatalog(gaiaCat);
    } catch (e) {
      console.warn("Gaia overlay failed", e);
      $("meta").textContent = "Gaia overlay unavailable (CORS/network)";
    }
  }

  async function pollJob(jobId) {
    for (;;) {
      const job = await (await fetch(`/api/job/${jobId}`)).json();
      const pct = job.total ? Math.round((100 * (job.progress || 0)) / job.total) : 0;
      $("info").textContent = `Preparing frames… ${job.progress || 0}/${job.total || "?"} (${job.status}) ${pct}%`;
      if (job.status === "ready") return job;
      if (job.status === "error") throw new Error(job.error || "job failed");
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  async function load() {
    history.pushState(null, "", "?" + qs());
    $("info").textContent = "Querying IRSA…";
    setBadge("unknown");
    clearInterval(timer);
    imgs = [];
    frames = [];
    idx = 0;

    const a = (Number($("stretch").value) / 100).toFixed(2);
    const prep = await (await fetch(`/api/prepare?${qs()}&a=${a}&max_frames=10`)).json();
    setBadge(prep.source, prep.warning);
    frames = prep.frames || [];
    if (!frames.length) {
      $("info").textContent = "No frames";
      return;
    }

    if (prep.async && prep.job_id) {
      await pollJob(prep.job_id);
    }

    imgs = frames.map((f) => {
      const im = new Image();
      im.src = `/api/frame/${encodeURIComponent(f.id)}?${qs()}&a=${a}&invert=1&align=1`;
      return im;
    });

    await Promise.all(
      imgs.map(
        (im) =>
          new Promise((resolve) => {
            if (im.complete) resolve();
            else {
              im.onload = resolve;
              im.onerror = resolve;
            }
          })
      )
    );

    gotoAladin();
    if ($("gaia").checked) toggleGaia();
    showFrame();
    loadMeta(frames[0].id);
    playing = true;
    $("play").textContent = "Pause";
    play();
  }

  async function resolveName() {
    const name = $("name").value.trim();
    if (!name) return;
    const r = await fetch(`/api/resolve?name=${encodeURIComponent(name)}`);
    if (!r.ok) {
      $("info").textContent = await r.text();
      return;
    }
    const data = await r.json();
    $("ra").value = data.ra.toFixed(6);
    $("dec").value = data.dec.toFixed(6);
    load();
  }

  async function loadPresets() {
    const r = await fetch("/api/targets");
    const data = await r.json();
    const sel = $("preset");
    sel.innerHTML = '<option value="">Presets…</option>';
    for (const t of data.targets) {
      const o = document.createElement("option");
      o.value = JSON.stringify(t);
      o.textContent = t.name;
      sel.appendChild(o);
    }
  }

  function initAladin() {
    if (!window.A) return;
    A.init.then(() => {
      aladin = A.aladin("#aladin-lite-div", {
        survey: "P/DSS2/color",
        fov: 0.5,
        target: `${$("ra").value} ${$("dec").value}`,
        showCooGrid: false,
        showProjectionControl: false,
        showFullscreenControl: true,
      });
    });
  }

  function toggleWise() {
    if (!aladin) return;
    try {
      if ($("wise").checked) {
        // AllWISE / unWISE-style infrared context when available in HiPS
        aladin.setImageSurvey("P/allWISE/color");
      } else {
        aladin.setImageSurvey("P/DSS2/color");
      }
    } catch (e) {
      console.warn("WISE survey switch failed", e);
      $("meta").textContent = "WISE HiPS unavailable; keeping DSS";
    }
  }

  // Wire controls
  $("go").onclick = load;
  $("resolve").onclick = resolveName;
  $("play").onclick = () => {
    playing = !playing;
    $("play").textContent = playing ? "Pause" : "Play";
    if (playing) play();
    else clearInterval(timer);
  };
  $("speed").oninput = play;
  $("stretch").onchange = load;
  $("gaia").onchange = toggleGaia;
  $("wise").onchange = toggleWise;
  $("diffMode").onchange = () => {
    clearInterval(timer);
    showFrame();
    if (!$("diffMode").checked && playing) play();
  };
  $("gif").onclick = () => {
    window.open(`/api/gif?${qs()}&speed=${$("speed").value}`, "_blank");
  };
  $("preset").onchange = () => {
    const v = $("preset").value;
    if (!v) return;
    const t = JSON.parse(v);
    $("name").value = t.name;
    $("ra").value = t.ra;
    $("dec").value = t.dec;
    load();
  };

  // URL params on load
  const q = new URLSearchParams(location.search);
  for (const k of ["ra", "dec", "fov", "band", "mode", "speed"]) {
    if (q.has(k) && $(k)) $(k).value = q.get(k);
  }
  if (q.get("gaia") === "1") $("gaia").checked = true;
  if (q.get("diff") === "1") $("diffMode").checked = true;
  if (q.has("a")) $("stretch").value = String(Math.round(Number(q.get("a")) * 100));

  initAladin();
  loadPresets();
  if (q.has("ra") || true) load();
})();
