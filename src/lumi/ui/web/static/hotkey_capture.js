// Hotkey-capture input.
//
// Wires up #hotkey-input and #hotkey-reset on the page:
//   - Click the input → it goes into "listening" mode.
//   - Press any combination → modifiers + key are recorded as "cmd+shift+l".
//   - The value is stored in the input so it submits with the form.
//   - The reset button restores the data-default value (platform default).
//
// Keys captured but ignored:
//   - Lone modifiers (e.g. just Shift)
//   - Combinations without a non-modifier key
//   - Escape (cancels listening)

(function () {
  const input = document.getElementById("hotkey-input");
  const reset = document.getElementById("hotkey-reset");
  if (!input) return;

  let listening = false;

  function setListening(on) {
    listening = on;
    if (on) {
      input.dataset.prev = input.value;
      input.value = "press keys…";
      input.style.outline = "2px solid var(--iris-accent, #FF4D8F)";
    } else {
      input.style.outline = "";
    }
  }

  input.addEventListener("click", () => setListening(true));
  input.addEventListener("blur", () => {
    if (listening && input.value === "press keys…") {
      input.value = input.dataset.prev || input.dataset.default || "";
    }
    setListening(false);
  });

  input.addEventListener("keydown", (e) => {
    if (!listening) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === "Escape") {
      input.value = input.dataset.prev || input.dataset.default || "";
      setListening(false);
      input.blur();
      return;
    }
    const parts = [];
    if (e.metaKey) parts.push("cmd");
    if (e.ctrlKey) parts.push("ctrl");
    if (e.altKey) parts.push("alt");
    if (e.shiftKey) parts.push("shift");
    if (["Meta", "Control", "Alt", "Shift"].includes(e.key)) {
      // modifier alone — keep listening
      input.value = parts.join("+") + "+…";
      return;
    }
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase();
    parts.push(k);
    input.value = parts.join("+");
    setListening(false);
    input.blur();
  });

  if (reset) {
    reset.addEventListener("click", () => {
      input.value = input.dataset.default || "";
    });
  }
})();
