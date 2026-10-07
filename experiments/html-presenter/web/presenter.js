"use strict";

const elements = Object.fromEntries([
  "deck", "stage", "start", "close", "end", "fullscreen", "audience", "previous", "next",
  "slide-position", "slide-title", "connection-label", "status-dot", "join-code",
  "join-note", "copy-code", "stage-code", "projected-code", "activity-note", "error",
  "response-count", "participant-count", "votes", "log", "region", "sync-status",
].map(id => [id, document.getElementById(id)]));

let boot;
let state;
let reveal;
let selected = { slide_index: 0, fragment_index: -1 };
let busy = false;
let localError = "";
let queuedSync = null;
let syncTimer;
let polling = false;
let lastLog = "";
const audienceChannel = new BroadcastChannel("deckgen-audience");

function broadcastAudience() {
  if (!boot || !state || !reveal?.isReady()) return;
  const current = reveal.getState();
  audienceChannel.postMessage({
    type: "slide", title: boot.title, deck_url: boot.deck_url,
    reveal: { indexh: current.indexh, indexv: current.indexv, indexf: current.indexf, paused: current.paused },
    class_code: state.class_code,
  });
}

audienceChannel.addEventListener("message", event => {
  if (event.data?.type === "ready") broadcastAudience();
});
setInterval(broadcastAudience, 1000);
window.addEventListener("beforeunload", () => audienceChannel.postMessage({ type: "disconnected" }));

function selection() {
  const indices = reveal.getIndices();
  return { slide_index: indices.h, fragment_index: Number.isInteger(indices.f) ? indices.f : -1 };
}

function canOpenQuestion() {
  const slide = boot?.slides[selected.slide_index];
  return Boolean(reveal && slide?.activity?.type === "multiple_choice"
    && !busy && state.phase !== "starting"
    && !(state.phase === "error" && state.can_end)
    && !(state.phase === "open" && state.active_slide === selected.slide_index));
}

function render() {
  if (!boot || !state) return;
  const slide = boot.slides[selected.slide_index];
  const multipleChoice = slide?.activity?.type === "multiple_choice";
  const sameActivity = state.active_slide === selected.slide_index;
  const working = busy || state.phase === "starting";
  elements["connection-label"].textContent = {
    idle: "Ready / no remote connection", starting: "Starting class and question...",
    open: "Live / submissions open", closed: "Live / submissions closed",
    ended: "Class ended", error: "Session needs attention",
  }[state.phase] || state.phase;
  elements["status-dot"].className = `status-dot${state.phase === "error" ? " error" : state.connected ? " live" : ""}`;
  elements["join-code"].textContent = state.class_code || "No class started";
  elements["join-code"].classList.toggle("empty", !state.class_code);
  elements["projected-code"].textContent = state.class_code || "";
  elements["copy-code"].hidden = !state.class_code;
  elements["stage-code"].hidden = !state.class_code;
  elements["join-note"].textContent = state.class_code
    ? "Students use the existing ClassPoint app. This browser is the presenter."
    : state.expected_class_code ? `Start the ${state.expected_class_code} class from here. Close PowerPoint first.`
    : "Close PowerPoint, then start the class from here. This uses the instructor profile from your own capture.";
  elements.start.disabled = !canOpenQuestion();
  elements.start.textContent = working ? "Working..." : !state.can_end ? state.phase === "error" ? "Retry class + question" : "Start class + question" : state.phase === "open" && sameActivity ? "Question open" : "Open this question";
  elements.close.disabled = working || state.phase !== "open";
  elements.end.disabled = working || !state.can_end;
  elements.previous.disabled = !reveal || working || reveal.isFirstSlide();
  elements.next.disabled = !reveal || working || reveal.isLastSlide();
  elements.fullscreen.disabled = !reveal;
  elements.audience.disabled = !reveal;
  elements["slide-position"].textContent = `${selected.slide_index + 1} / ${boot.slides.length}`;
  elements["slide-title"].textContent = slide?.title || "";
  elements["activity-note"].textContent = multipleChoice
    ? "You can also click the multiple-choice badge inside the slide."
    : "This slide has no supported multiple-choice activity. Navigate to a multiple-choice slide.";
  const problem = localError || state.error;
  elements.error.hidden = !problem;
  elements.error.textContent = problem || "";
  const responseCount = state.responses.length;
  elements["response-count"].textContent = responseCount ? `${responseCount} response${responseCount === 1 ? "" : "s"}` : "No responses yet";
  elements["participant-count"].textContent = state.participants ? `${state.participants} student${state.participants === 1 ? "" : "s"} connected` : "No students connected";
  const choices = state.activity_choices.length ? state.activity_choices : multipleChoice ? slide.activity.choices : [];
  const voteNodes = choices.map(choice => {
    const count = state.responses.filter(answer => answer.includes(choice)).length;
    const row = document.createElement("div");
    row.className = "vote";
    const label = document.createElement("span");
    label.className = "vote-label";
    label.textContent = choice;
    label.title = choice;
    const track = document.createElement("div");
    track.className = "vote-track";
    const fill = document.createElement("div");
    fill.className = "vote-fill";
    fill.style.width = `${responseCount ? count / responseCount * 100 : 0}%`;
    track.append(fill);
    const total = document.createElement("span");
    total.className = "vote-count";
    total.textContent = count;
    row.setAttribute("aria-label", `Choice ${choice}: ${count} responses`);
    row.append(label, track, total);
    return row;
  });
  if (!voteNodes.length) {
    const empty = document.createElement("p");
    empty.className = "empty-votes";
    empty.textContent = "Open a multiple-choice question to collect answers.";
    voteNodes.push(empty);
  }
  elements.votes.replaceChildren(...voteNodes);
  elements.region.textContent = state.region;
  const serializedLog = JSON.stringify(state.log);
  if (serializedLog !== lastLog) {
    lastLog = serializedLog;
    elements.log.replaceChildren(...state.log.map(entry => {
      const item = document.createElement("li");
      const time = document.createElement("time");
      time.textContent = entry.time;
      const message = document.createElement("span");
      message.textContent = entry.message;
      item.append(time, message);
      return item;
    }));
  }
  broadcastAudience();
}

async function send(action, body = {}) {
  const response = await fetch(`/api/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Presenter-Token": boot.token },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The local presenter rejected the command.");
  state = result;
  return result;
}

async function run(action) {
  if (busy) return;
  if (["start", "activity"].includes(action)) {
    if (!canOpenQuestion()) return;
    queuedSync = null;
    clearTimeout(syncTimer);
  }
  busy = true;
  localError = "";
  render();
  try {
    await send(action, selected);
  } catch (error) {
    localError = error.message;
  } finally {
    busy = false;
    render();
    drainSync();
  }
}

async function drainSync() {
  if (busy || !queuedSync || !state?.can_end || !["open", "closed"].includes(state.phase)) return;
  const latest = queuedSync;
  queuedSync = null;
  busy = true;
  elements["sync-status"].textContent = "Sending slide...";
  render();
  try {
    await send("sync", latest);
    elements["sync-status"].textContent = "Slide sent";
  } catch (error) {
    localError = error.message;
    elements["sync-status"].textContent = "Slide not sent";
  } finally {
    busy = false;
    render();
    if (queuedSync) drainSync();
  }
}

function slideChanged() {
  selected = selection();
  render();
  if (state?.can_end) {
    queuedSync = { ...selected };
    clearTimeout(syncTimer);
    syncTimer = setTimeout(drainSync, 300);
  }
}

async function connectDeck() {
  const windowInside = elements.deck.contentWindow;
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (windowInside.Reveal?.isReady()) break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  reveal = windowInside.Reveal;
  if (!reveal?.isReady()) throw new Error("Deckgen's Reveal.js did not load. Check the local deck assets.");
  reveal.slide(boot.initial_slide);
  reveal.on("slidechanged", slideChanged);
  reveal.on("fragmentshown", slideChanged);
  reveal.on("fragmenthidden", slideChanged);
  windowInside.document.querySelectorAll("[data-classpoint]").forEach(marker => {
    const index = Number(marker.closest("section[data-slide]")?.dataset.slide) - 1;
    if (boot.slides[index]?.activity?.type !== "multiple_choice") return;
    marker.setAttribute("role", "button");
    marker.setAttribute("tabindex", "0");
    marker.removeAttribute("href");
    marker.setAttribute("aria-label", "Open this multiple-choice question in ClassPoint");
    marker.style.cursor = "pointer";
    const open = event => {
      event.preventDefault();
      event.stopPropagation();
      selected = selection();
      if (!canOpenQuestion()) return;
      run(state.can_end ? "activity" : "start");
    };
    marker.addEventListener("click", open);
    marker.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") open(event);
    });
  });
  const focusStyle = windowInside.document.createElement("style");
  focusStyle.textContent = "#ho-open,#ho-deck{display:none!important}[data-classpoint][role=button]:focus-visible{outline:4px solid #00544c;outline-offset:6px}";
  windowInside.document.head.append(focusStyle);
  slideChanged();
}

async function poll() {
  if (polling || !boot || busy) return;
  polling = true;
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error("The local bridge is unavailable.");
    const latest = await response.json();
    if (!busy) {
      state = latest;
      render();
    }
  } catch {
    localError = "Lost the local bridge. Keep the presenter.py terminal running, then reload this page.";
    render();
  } finally {
    polling = false;
  }
}

elements.start.addEventListener("click", () => run(state.can_end ? "activity" : "start"));
elements.close.addEventListener("click", () => run("close"));
elements.end.addEventListener("click", () => {
  queuedSync = null;
  run("end");
});
elements.previous.addEventListener("click", () => reveal?.prev());
elements.next.addEventListener("click", () => reveal?.next());
elements.audience.addEventListener("click", () => {
  const audience = window.open("/assets/audience.html", "deckgen-audience", "popup,width=1280,height=720");
  if (!audience) {
    localError = "Allow popups for the local presenter, then open the audience screen again.";
    render();
  }
});
elements.fullscreen.addEventListener("click", async () => {
  try {
    await elements.stage.requestFullscreen();
    elements.deck.contentWindow.focus();
  } catch {
    localError = "This browser could not enter full screen. You can still present in this window.";
    render();
  }
});
elements["copy-code"].addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(String(state.class_code));
    elements["copy-code"].textContent = "Copied";
    setTimeout(() => { elements["copy-code"].textContent = "Copy code"; }, 1200);
  } catch {
    localError = "Clipboard access is unavailable. Copy the displayed join code manually.";
    render();
  }
});

async function initialize() {
  try {
    const response = await fetch("/api/bootstrap", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load the local presenter.");
    boot = await response.json();
    state = boot.state;
    selected.slide_index = boot.initial_slide;
    document.title = `${boot.title} / ClassPoint presenter`;
    localStorage.setItem("deckgen.view", "deck");
    elements.deck.addEventListener("load", () => connectDeck().catch(error => {
      localError = error.message;
      render();
    }), { once: true });
    elements.deck.src = boot.deck_url;
    render();
    setInterval(poll, 750);
  } catch (error) {
    elements["connection-label"].textContent = "Local presenter unavailable";
    elements.error.hidden = false;
    elements.error.textContent = error.message;
  }
}

initialize();
