const form = document.querySelector("#caption-form");
const fileInput = document.querySelector("#video-input");
const fileLabel = document.querySelector("#file-label");
const submitButton = document.querySelector("#submit-button");
const status = document.querySelector("#status");
const result = document.querySelector("#result");
const captionHeading = document.querySelector("#caption-heading");
const meta = document.querySelector("#meta");
const frameCaptions = document.querySelector("#frame-captions");
const dropZone = document.querySelector("#drop-zone");
const downloadButton = document.querySelector("#download-button");
const historySection = document.querySelector("#history");
const historyList = document.querySelector("#history-list");
const clearHistoryButton = document.querySelector("#clear-history");
const videoPlayerSection = document.querySelector("#video-player-section");
const videoPreview = document.querySelector("#video-preview");
const narrationButton = document.querySelector("#narration-button");
const narrationRate = document.querySelector("#narration-rate");
const audioDescriptions = document.querySelector("#audio-descriptions");
const HISTORY_KEY = "video-caption-generator-history-v1";
let activeDescriptions = [];
let spokenDescriptionIndexes = new Set();
let narrationEnabled = false;
let previewUrl = null;
let isDescriptionPause = false;

function getHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
  } catch {
    return [];
  }
}

function renderHistory() {
  const entries = getHistory();
  historyList.replaceChildren(
    ...entries.map(({ caption, createdAt }) => {
      const item = document.createElement("li");
      const date = new Date(createdAt).toLocaleString();
      item.textContent = `${caption} — ${date}`;
      return item;
    }),
  );
  historySection.classList.toggle("hidden", entries.length === 0);
}

function saveToHistory(data) {
  const entries = getHistory();
  entries.unshift({
    caption: data.caption,
    createdAt: new Date().toISOString(),
  });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, 8)));
  renderHistory();
}

function showSelectedFile(file) {
  fileLabel.textContent = file ? file.name : "Choose a video";
  window.speechSynthesis.cancel();
  narrationEnabled = false;
  narrationButton.disabled = true;
  narrationButton.textContent = "Play with audio descriptions";
  activeDescriptions = [];
  spokenDescriptionIndexes = new Set();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  if (file) {
    previewUrl = URL.createObjectURL(file);
    videoPreview.src = previewUrl;
    videoPlayerSection.classList.remove("hidden");
  } else {
    videoPreview.removeAttribute("src");
    videoPlayerSection.classList.add("hidden");
  }
}

function setStatus(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function showResult(data) {
  captionHeading.textContent = data.caption;
  meta.textContent = `${data.sampled_frames} visual moments analysed · ${data.audio_descriptions.length} essential descriptions · running on ${data.device.toUpperCase()}`;
  frameCaptions.replaceChildren(
    ...data.frame_captions.map(({ timestamp_seconds: seconds, caption, summary_status: summaryStatus }) => {
      const item = document.createElement("li");
      const label = {
        main_scene: "main visual scene",
        additional_scene: "additional visual scene",
        ignored: "ignored: likely outro/logo",
      }[summaryStatus] || "detected visual scene";
      item.textContent = `${seconds.toFixed(2)}s — ${caption} (${label})`;
      item.classList.toggle("key-moment", summaryStatus === "main_scene");
      item.classList.toggle("additional-scene", summaryStatus === "additional_scene");
      return item;
    }),
  );
  activeDescriptions = data.audio_descriptions;
  spokenDescriptionIndexes = new Set();
  audioDescriptions.replaceChildren(
    ...activeDescriptions.map(({ timestamp_seconds: seconds, description }) => {
      const item = document.createElement("li");
      item.textContent = `${seconds.toFixed(2)}s — ${description}`;
      return item;
    }),
  );
  narrationButton.disabled = activeDescriptions.length === 0;
  result.classList.remove("hidden");
  saveToHistory(data);
}

function stopNarration() {
  narrationEnabled = false;
  isDescriptionPause = false;
  window.speechSynthesis.cancel();
  narrationButton.textContent = "Play with audio descriptions";
}

function speakDueDescription() {
  if (!narrationEnabled || window.speechSynthesis.speaking) return;
  const nextIndex = activeDescriptions.findIndex(
    ({ timestamp_seconds: seconds }, index) => !spokenDescriptionIndexes.has(index) && seconds <= videoPreview.currentTime + 0.35,
  );
  if (nextIndex === -1) return;

  const utterance = new SpeechSynthesisUtterance(activeDescriptions[nextIndex].description);
  utterance.rate = Number(narrationRate.value);
  utterance.volume = 1;
  utterance.lang = "en-US";
  spokenDescriptionIndexes.add(nextIndex);
  isDescriptionPause = true;
  videoPreview.pause();
  const resumeVideo = () => {
    isDescriptionPause = false;
    if (narrationEnabled && !videoPreview.ended) {
      videoPreview.play().catch(() => {
        setStatus("Press play to continue the video after the description.", true);
      });
    }
  };
  utterance.onend = resumeVideo;
  utterance.onerror = resumeVideo;
  window.speechSynthesis.speak(utterance);
}

fileInput.addEventListener("change", () => showSelectedFile(fileInput.files[0]));

["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
});

dropZone.addEventListener("drop", (event) => {
  const [file] = event.dataTransfer.files;
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  showSelectedFile(file);
});

narrationButton.addEventListener("click", async () => {
  if (narrationEnabled) {
    stopNarration();
    return;
  }
  narrationEnabled = true;
  spokenDescriptionIndexes = new Set(
    activeDescriptions
      .map(({ timestamp_seconds: seconds }, index) => (seconds < videoPreview.currentTime - 0.35 ? index : null))
      .filter((index) => index !== null),
  );
  narrationButton.textContent = "Stop audio descriptions";
  try {
    await videoPreview.play();
    speakDueDescription();
  } catch {
    setStatus("Press play on the video, then turn on audio descriptions.", true);
  }
});

videoPreview.addEventListener("timeupdate", speakDueDescription);
videoPreview.addEventListener("seeking", () => {
  window.speechSynthesis.cancel();
  isDescriptionPause = false;
  spokenDescriptionIndexes = new Set(
    activeDescriptions
      .map(({ timestamp_seconds: seconds }, index) => (seconds < videoPreview.currentTime - 0.35 ? index : null))
      .filter((index) => index !== null),
  );
});
videoPreview.addEventListener("pause", () => {
  if (!isDescriptionPause) window.speechSynthesis.cancel();
});
videoPreview.addEventListener("ended", stopNarration);

downloadButton.addEventListener("click", () => {
  const frameDetails = [...frameCaptions.querySelectorAll("li")]
    .map((item) => `- ${item.textContent}`)
    .join("\n");
  const narrationScript = [...audioDescriptions.querySelectorAll("li")]
    .map((item) => `- ${item.textContent}`)
    .join("\n");
  const content = `Video Caption Generator\n\nCaption: ${captionHeading.textContent}\n${meta.textContent}\n\nAudio-description script:\n${narrationScript}\n\nDetected moments:\n${frameDetails}\n`;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
  link.download = "video-caption-result.txt";
  link.click();
  URL.revokeObjectURL(link.href);
});

clearHistoryButton.addEventListener("click", () => {
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const [file] = fileInput.files;
  if (!file) {
    setStatus("Choose a video first.", true);
    return;
  }

  submitButton.disabled = true;
  result.classList.add("hidden");
  setStatus("Reading the video and generating visual captions… First use downloads the AI model.");

  try {
    const body = new FormData();
    body.append("video", file);
    const response = await fetch("/api/caption", { method: "POST", body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Caption generation failed.");
    showResult(data);
    setStatus("Done.");
  } catch (error) {
    setStatus(error.message || "Something went wrong. Try another short video.", true);
  } finally {
    submitButton.disabled = false;
  }
});

renderHistory();
