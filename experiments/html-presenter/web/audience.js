"use strict";

const deck = document.getElementById("deck");
const join = document.getElementById("join");
const code = document.getElementById("join-code");
const notice = document.getElementById("notice");
const channel = new BroadcastChannel("deckgen-audience");
let pending;
let reveal;
let source;
let lastSeen = 0;

function apply() {
  if (!pending || !reveal?.isReady()) return;
  reveal.setState({ ...pending.reveal, overview: false });
  code.textContent = pending.class_code || "";
  join.hidden = !pending.class_code;
  notice.hidden = true;
}

deck.addEventListener("load", async () => {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    reveal = deck.contentWindow.Reveal;
    if (reveal?.isReady()) break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  if (!reveal?.isReady()) {
    notice.textContent = "The audience slides could not load. Reopen this window from the presenter.";
    notice.hidden = false;
    return;
  }
  reveal.configure({ keyboard: false, touch: false, controls: false, progress: false });
  const style = deck.contentDocument.createElement("style");
  style.textContent = "#ho-open,#ho-deck,.controls,.progress,.cp{display:none!important}";
  deck.contentDocument.head.append(style);
  apply();
});

channel.addEventListener("message", event => {
  const message = event.data;
  if (message?.type === "disconnected") {
    notice.textContent = "Presenter disconnected. Slides will resume when it returns.";
    notice.hidden = false;
    return;
  }
  if (message?.type !== "slide" || !message.reveal || typeof message.deck_url !== "string") return;
  const url = new URL(message.deck_url, location.origin);
  if (url.origin !== location.origin || !url.pathname.startsWith("/deck/")) return;
  pending = message;
  lastSeen = Date.now();
  document.title = `${message.title} / Audience`;
  if (source !== url.href) {
    source = url.href;
    reveal = undefined;
    localStorage.setItem("deckgen.view", "deck");
    deck.src = url.href;
  } else {
    apply();
  }
});

function ready() { channel.postMessage({ type: "ready" }); }
ready();
setInterval(() => {
  ready();
  if (lastSeen && Date.now() - lastSeen > 8000) {
    notice.textContent = "Presenter disconnected. Slides will resume when it returns.";
    notice.hidden = false;
  }
}, 1000);

document.addEventListener("keydown", async event => {
  if (event.key.toLowerCase() !== "f") return;
  if (document.fullscreenElement) await document.exitFullscreen();
  else await document.documentElement.requestFullscreen();
});
