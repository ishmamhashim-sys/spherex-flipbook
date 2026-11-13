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

  // Absolute HiPS URLs (IRSA mirrors). CDS IDs like "P/DSS2/color" fall back to
  // relative paths on this origin when MocServer resolution fails → empty map.
  const HIPS_DSS = "https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color";
  const HIPS_WISE = "https://skies.esac.esa.int/AllWISEColor";

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
      sigma: $("sigma") ? $("sigma").value : "3",
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

  function hideAnomalies() {
    const panel = $("anomPanel");
    if (panel) panel.classList.add("hidden");
    const body = $("anomBody");
    if (body) body.innerHTML = "";
  }

  function renderAnomalies(data) {
    const panel = $("anomPanel");
    if (!panel) return;
    panel.classList.remove("hidden");
    const n = data.anomalies_count || (data.anomalies || []).length;
    $("anomCount").textContent = `${n} anomal${n === 1 ? "y" : "ies"}`;
    const st = data.stats || {};
    $("anomStats").textContent = st.std != null
      ? `ΔMJD ${data.delta_mjd ?? "—"} · σ=${Number(st.std).toExponential(2)} · thresh ${st.sigma_threshold}σ`
      : "";
    const body = $("anomBody");
    body.innerHTML = "";
    const rows = data.anomalies || [];
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="4">No peaks above threshold</td></tr>';
      return;
    }
    for (const row of rows.slice(0, 40)) {
      const tr = document.createElement("tr");
      const pos = String(row.type || "").includes("Positive");
      tr.innerHTML = `
        <td class="${pos ? "pos" : "neg"}">${row.snr > 0 ? "+" : ""}${Number(row.snr).toFixed(2)}σ</td>
        <td>${pos ? "New/bright" : "Faded/moved"}</td>
        <td>${Number(row.ra).toFixed(5)}</td>
        <td>${Number(row.dec).toFixed(5)}</td>`;
      body.appendChild(tr);
    }
  }

  async function runSubtract() {
    if (frames.length < 2) {
      $("info").textContent = "Difference imaging needs at least 2 frames";
      hideAnomalies();
      if (imgs.length) $("view").src = imgs[idx].src;
      return;
    }
    const idA = frames[0].id;
    const idB = frames[1].id;
    const sigma = $("sigma") ? $("sigma").value : "3";
    $("info").textContent = `diff ${idA} − ${idB} · detecting anomalies…`;
    updateLegend();
    $("view").src = `/api/diff?id_a=${encodeURIComponent(idA)}&id_b=${encodeURIComponent(idB)}&${qs()}`;
    try {
      const url =
        `/api/subtract?id_a=${encodeURIComponent(idA)}&id_b=${encodeURIComponent(idB)}` +
        `&${qs()}&sigma_thresh=${encodeURIComponent(sigma)}`;
      const data = await (await fetch(url)).json();
      if (data.status !== "success") {
        $("info").textContent = data.detail || "subtract failed";
        hideAnomalies();
        return;
      }
      $("info").textContent =
        `diff ${idA} − ${idB} · ${data.anomalies_count} anomalies · ΔMJD ${data.delta_mjd}`;
      renderAnomalies(data);
      if (data.diff_png_url) $("view").src = data.diff_png_url;
    } catch (e) {
      console.warn("subtract failed", e);
      $("info").textContent = `diff ${idA} − ${idB} · anomaly lookup failed`;
      hideAnomalies();
    }
  }

  function showFrame() {
    if (!imgs.length) return;
    if ($("diffMode").checked) {
      runSubtract();
      return;
    }
    hideAnomalies();
    $("view").src = imgs[idx].src;
    const fr = frames[idx];
    $("info").textContent = `frame ${idx + 1}/${frames.length} · MJD ${Number(fr.mjd).toFixed(3)} · ${fr.band}`;
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

  function setMapStatus(text, hide) {
    const el = $("mapStatus");
    if (!el) return;
    if (hide) {
      el.classList.add("hidden");
      return;
    }
    el.classList.remove("hidden");
    el.textContent = text;
  }

  function gotoAladin() {
    if (!aladin) return;
    const ra = Number($("ra").value);
    const dec = Number($("dec").value);
    const fov = Number($("fov").value);
    try {
      aladin.gotoRaDec(ra, dec);
      aladin.setFov(Math.max(fov * 4, 0.35));
      // Nudge a redraw after layout / async tile fetch
      if (aladin.view && typeof aladin.view.requestRedraw === "function") {
        aladin.view.requestRedraw();
      }
      window.dispatchEvent(new Event("resize"));
    } catch (e) {
      console.warn("gotoAladin failed", e);
    }
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
    hideAnomalies();
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
    setMapStatus("Loading sky map…", false);
    if (!window.A || !A.init) {
      setMapStatus("Sky map library failed to load. Blink panel still works.", false);
      return;
    }
    const ra = Number($("ra").value);
    const dec = Number($("dec").value);
    A.init
      .then(() => {
        // Give the panel a real laid-out size before creating the WebGL view
        const host = $("aladin-lite-div");
        if (host && host.clientHeight < 100) {
          host.style.height = "480px";
        }
        aladin = A.aladin("#aladin-lite-div", {
          survey: HIPS_DSS,
          fov: 0.75,
          target: `${ra} ${dec}`,
          cooFrame: "ICRSd",
          showCooGrid: false,
          showProjectionControl: false,
          showFullscreenControl: true,
          showLayersControl: false,
          showGotoControl: false,
          showFrame: false,
          reticleColor: "#3dd6c6",
          reticleSize: 22,
        });
        setMapStatus("", true);
        // Second-pass goto after tiles start; helps empty-first-paint cases
        setTimeout(() => {
          gotoAladin();
          setMapStatus("", true);
        }, 400);
      })
      .catch((err) => {
        console.warn("Aladin init failed", err);
        setMapStatus(
          "Sky map unavailable (network/CDN). Use the blink panel on the right for science.",
          false
        );
      });
  }

  function toggleWise() {
    if (!aladin) return;
    try {
      if ($("wise").checked) {
        aladin.setImageSurvey(HIPS_WISE);
      } else {
        aladin.setImageSurvey(HIPS_DSS);
      }
      setTimeout(gotoAladin, 200);
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
    if ($("diffMode").checked && frames.length < 2) {
      $("info").textContent = "Difference imaging needs at least 2 frames";
      hideAnomalies();
    }
    showFrame();
    if (!$("diffMode").checked && playing) play();
  };
  if ($("sigma")) {
    $("sigma").onchange = () => {
      if ($("diffMode").checked) runSubtract();
    };
  }
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
  if (q.has("sigma") && $("sigma")) $("sigma").value = q.get("sigma");

  initAladin();
  loadPresets();
  // Always load: form fields already hold defaults (WISE 0855) or URL overrides.
  load();
})();
