"use strict";

class AnswerPanel {
  constructor(parent, { dismiss, finish, close, scroll } = {}) {
    this.root = document.createElement("section");
    this.root.className = "answer-panel";
    this.root.hidden = true;
    this.root.setAttribute("aria-label", "ClassPoint answers");
    this.root.innerHTML = `<header class="answer-header"><div><h2></h2><p class="answer-count" role="status"></p></div></header><ol class="answer-list" tabindex="0" aria-label="Submitted answers"></ol><footer class="answer-footer"><p class="answer-status" role="status"></p></footer>`;
    this.title = this.root.querySelector("h2");
    this.count = this.root.querySelector(".answer-count");
    this.list = this.root.querySelector("ol");
    this.status = this.root.querySelector(".answer-status");
    this.lastKey = "";
    this.activity = null;
    if (dismiss) {
      const button = document.createElement("button");
      button.className = "quiet";
      button.type = "button";
      button.textContent = "Hide answers";
      button.addEventListener("click", dismiss);
      this.root.querySelector("header").append(button);
    }
    if (finish) {
      this.close = document.createElement("button");
      this.close.className = "quiet";
      this.close.type = "button";
      this.close.textContent = "Close submissions only";
      this.close.addEventListener("click", close);
      this.finish = document.createElement("button");
      this.finish.id = "finish-question";
      this.finish.className = "primary";
      this.finish.type = "button";
      this.finish.addEventListener("click", () => this.hasRespondents ? finish() : close());
      this.root.querySelector("footer").append(this.close, this.finish);
    }
    if (scroll) this.list.addEventListener("scroll", scroll, { passive: true });
    parent.append(this.root);
  }

  update(data, busy = false) {
    this.root.hidden = !data?.visible;
    if (!data) return;
    this.title.textContent = data.title || "ClassPoint answers";
    const responses = data.responses || [];
    this.count.textContent = `${responses.length} answer${responses.length === 1 ? "" : "s"}${data.limited ? " (local limit reached)" : ""}`;
    const key = JSON.stringify([data.activity, data.phase, responses]);
    if (key !== this.lastKey) {
      this.lastKey = key;
      const top = this.activity === data.activity ? this.list.scrollTop : 0;
      this.activity = data.activity;
      this.list.replaceChildren(...responses.map((answer, index) => {
        const row = document.createElement("li");
        row.className = "answer-row";
        const number = document.createElement("span");
        number.className = "answer-number";
        number.textContent = String(index + 1).padStart(2, "0");
        const text = document.createElement("p");
        text.textContent = answer.text ?? answer.caption ?? "";
        row.append(number, text);
        return row;
      }));
      if (!responses.length) {
        const empty = document.createElement("li");
        empty.className = "answer-empty";
        empty.textContent = data.phase === "open" ? "Waiting for the first answer. Students can submit in ClassPoint." : "No answers for this question.";
        this.list.append(empty);
      }
      this.list.scrollTop = top;
    }
    const awarded = data.stars_status === "awarded";
    const uncertain = data.stars_status === "uncertain";
    this.status.textContent = data.error || (uncertain
      ? "Star award could not be confirmed. Check ClassPoint before awarding again."
      : awarded ? `1 star awarded to each of ${data.stars_count} respondents.`
      : data.phase === "closed" ? "Submissions closed. Answers remain on screen."
      : "Submissions are open. New answers appear here.");
    if (this.finish) {
      const hasRespondents = data.respondents > 0;
      this.hasRespondents = hasRespondents;
      this.finish.disabled = busy || awarded || uncertain || !["open", "closed"].includes(data.phase)
        || (data.phase === "closed" && !hasRespondents);
      this.finish.textContent = busy ? "Working..." : awarded ? `Star awarded to ${data.stars_count} respondents`
        : uncertain ? "Check stars in ClassPoint" : !hasRespondents
          ? data.phase === "closed" ? "No respondents to award" : "Close submissions"
          : data.phase === "closed" ? "Give each respondent 1 star" : "Close + give each respondent 1 star";
      this.close.disabled = busy || data.phase !== "open";
      this.close.textContent = data.phase === "closed" ? "Submissions closed" : "Close submissions only";
    }
  }

  scrollRatio() {
    const range = this.list.scrollHeight - this.list.clientHeight;
    return range > 0 ? this.list.scrollTop / range : 0;
  }

  applyScroll(ratio) {
    this.list.scrollTop = Math.max(0, Math.min(1, ratio || 0)) * (this.list.scrollHeight - this.list.clientHeight);
  }
}

window.AnswerPanel = AnswerPanel;
