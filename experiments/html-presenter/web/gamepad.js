"use strict";

class GamepadControls {
  constructor(action) {
    this.action = action;
    this.identity = null;
    this.previous = new Set();
    this.repeatAt = 0;
  }

  update(pads, now, visible = true) {
    const pad = Array.from(pads).find(item => item && item.connected !== false);
    if (!visible || !pad || pad.mapping !== "standard") {
      this.identity = null;
      this.previous.clear();
      return pad;
    }
    const pressed = index => Boolean(pad.buttons[index]?.pressed);
    const active = new Set();
    if (pressed(1) || pressed(5) || pressed(15)) active.add("next");
    if (pressed(2) || pressed(4) || pressed(14)) active.add("previous");
    if (pressed(3)) active.add("answers");
    if (pressed(0)) active.add("dismiss");
    if (pressed(12) || (pad.axes[1] ?? 0) < -0.55) active.add("up");
    if (pressed(13) || (pad.axes[1] ?? 0) > 0.55) active.add("down");
    const identity = `${pad.index}:${pad.id}`;
    if (this.identity === identity) {
      for (const action of active) {
        const scrolling = action === "up" || action === "down";
        if (!this.previous.has(action) || (scrolling && now >= this.repeatAt)) {
          this.action(action);
          if (scrolling) this.repeatAt = now + 150;
        }
      }
    }
    // Baseline on connection/focus so a held button cannot fire a surprise action.
    this.identity = identity;
    this.previous = active;
    return pad;
  }
}

if (typeof module !== "undefined") module.exports = { GamepadControls };
else window.GamepadControls = GamepadControls;
