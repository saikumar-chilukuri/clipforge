const $ = (id) => document.getElementById(id);

const STAGES = ["downloading", "transcribing", "analyzing", "rendering"];
let pollTimer = null;
let currentJobId = null;

/* ---------- settings ---------- */

async function loadSettings() {
  const res = await fetch("/api/settings");
  const s = await res.json();
  $("keyBadge").hidden = !s.has_key;
  $("apiKey").value = s.groq_api_key || "";
  $("keyStatus").style.color = "";
  $("keyStatus").textContent = s.has_key
    ? `Key loaded: ${s.key_masked}`
    : "No key yet — paste a free key from console.groq.com/keys";
  $("llmModel").value = s.llm_model;
  $("whisperModel").value = s.whisper_model;
  $("maxHeight").value = String(s.max_height);
  return s;
}

$("settingsBtn").onclick = () => { $("settingsModal").hidden = false; loadSettings(); };
$("closeSettings").onclick = () => { $("settingsModal").hidden = true; };
$("settingsModal").addEventListener("click", (e) => {
  if (e.target === $("settingsModal")) $("settingsModal").hidden = true;
});

$("saveSettings").onclick = async () => {
  const body = {
    groq_api_key: $("apiKey").value.trim(),
    llm_model: $("llmModel").value,
    whisper_model: $("whisperModel").value,
    max_height: parseInt($("maxHeight").value, 10),
  };
  try {
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || "Save failed");
    $("settingsModal").hidden = true;
    await loadSettings();
  } catch (err) {
    $("keyStatus").textContent = "⚠ " + err.message;
    $("keyStatus").style.color = "#f87171";
  }
};

/* ---------- job creation ---------- */

$("jobForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = $("urlInput").value.trim();
  const [minLen, maxLen] = $("lenRange").value.split(",").map(Number);
  $("formError").hidden = true;
  $("goBtn").disabled = true;
  $("goBtn").textContent = "Starting…";

  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        num_clips: parseInt($("numClips").value, 10),
        min_len: minLen,
        max_len: maxLen,
        layout: $("layout").value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not start the job.");
    currentJobId = data.id;
    showProgress();
    poll();
  } catch (err) {
    $("formError").textContent = err.message;
    $("formError").hidden = false;
  } finally {
    $("goBtn").disabled = false;
    $("goBtn").textContent = "Get clips";
  }
});

/* ---------- progress polling ---------- */

function showProgress() {
  $("hero").style.display = "none";
  $("resultsPanel").hidden = true;
  $("historyPanel").hidden = true;
  $("progressPanel").hidden = false;
  $("jobError").hidden = true;
}

function updateStages(stage, error) {
  const items = [...document.querySelectorAll("#stageList li")];
  const idx = STAGES.indexOf(stage);
  items.forEach((li) => {
    li.classList.remove("active", "done");
    const liIdx = STAGES.indexOf(li.dataset.stage);
    if (stage === "done" || liIdx < idx) li.classList.add("done");
    else if (liIdx === idx && stage !== "done") li.classList.add("active");
    if (error && liIdx === idx) li.classList.add("active");
  });
}

function poll() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!currentJobId) return clearInterval(pollTimer);
    try {
      const res = await fetch(`/api/jobs/${currentJobId}`);
      if (!res.ok) throw new Error("Job not found.");
      const job = await res.json();
      renderJob(job);
      if (job.stage === "done" || job.stage === "error") {
        clearInterval(pollTimer);
        loadHistory();
        if (job.stage === "done") showResults(job);
      }
    } catch (err) {
      clearInterval(pollTimer);
      $("jobError").textContent = err.message;
      $("jobError").hidden = false;
    }
  }, 1200);
}

function renderJob(job) {
  const pct = Math.round((job.progress || 0) * 100);
  $("barFill").style.width = `${pct}%`;
  $("progPct").textContent = `${pct}%`;
  const title = job.meta?.title || job.url;
  $("progTitle").textContent = title.length > 70 ? title.slice(0, 70) + "…" : title;
  $("progMsg").textContent = job.error || job.message || "";
  updateStages(job.stage, !!job.error);
  if (job.error) {
    $("jobError").textContent = job.error;
    $("jobError").hidden = false;
  }
}

/* ---------- results ---------- */

function showResults(job) {
  $("progressPanel").hidden = true;
  $("resultsPanel").hidden = false;
  $("resTitle").textContent = job.meta?.title || "Your clips";
  const mins = Math.round((job.meta?.duration || 0) / 60);
  $("resMeta").textContent = `${job.clips.length} clips · source is ${mins} min · 9:16 with burned captions`;

  const grid = $("clipGrid");
  grid.innerHTML = "";
  job.clips.forEach((clip) => {
    const card = document.createElement("div");
    card.className = "clip";
    const src = `/api/clips/${job.id}/${clip.file}`;
    const tags = (clip.hashtags || []).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
    card.innerHTML = `
      <video src="${src}" preload="metadata" controls playsinline muted></video>
      <div class="clip-body">
        <span class="clip-time">${clip.label} · ${clip.duration}s</span>
        <div class="clip-title">${escapeHtml(clip.title)}</div>
        ${clip.caption ? `<div class="clip-caption">${escapeHtml(clip.caption)}</div>` : ""}
        <div class="tags">${tags}</div>
        <div class="clip-actions">
          <a class="btn primary" href="${src}?download=1" download="${clip.file}">⬇ Download</a>
          <button class="btn" data-copy>Copy post</button>
        </div>
      </div>`;
    card.querySelector("[data-copy]").onclick = async (e) => {
      const post = [clip.hook || clip.title, clip.caption, (clip.hashtags || []).join(" ")]
        .filter(Boolean)
        .join("\n\n");
      await navigator.clipboard.writeText(post);
      e.target.textContent = "Copied ✓";
      setTimeout(() => (e.target.textContent = "Copy post"), 1500);
    };
    grid.appendChild(card);
  });
}

$("newJobBtn").onclick = () => {
  $("resultsPanel").hidden = true;
  $("progressPanel").hidden = true;
  $("hero").style.display = "";
  $("urlInput").value = "";
  $("urlInput").focus();
};

/* ---------- history ---------- */

async function loadHistory() {
  const res = await fetch("/api/jobs");
  const data = await res.json();
  const jobs = data.jobs || [];
  if (!jobs.length) return;
  $("historyPanel").hidden = false;
  const list = $("historyList");
  list.innerHTML = "";
  jobs.forEach((job) => {
    const item = document.createElement("div");
    item.className = "history-item";
    const when = new Date(job.created * 1000).toLocaleString([], {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
    item.innerHTML = `
      <div style="min-width:0">
        <div class="h-title">${escapeHtml(job.title || job.url)}</div>
        <div class="h-meta">${when}${job.clip_count ? ` · ${job.clip_count} clips` : ""}</div>
      </div>
      <span class="pill ${job.stage}">${job.stage}</span>`;
    item.onclick = async () => {
      const res2 = await fetch(`/api/jobs/${job.id}`);
      const full = await res2.json();
      currentJobId = full.id;
      if (full.stage === "done") showResults(full);
      else {
        showProgress();
        renderJob(full);
        if (!["done", "error"].includes(full.stage)) poll();
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    list.appendChild(item);
  });
}

/* ---------- utils ---------- */

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

loadSettings();
loadHistory();
