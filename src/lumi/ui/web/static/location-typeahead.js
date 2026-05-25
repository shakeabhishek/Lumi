// City autocomplete for the weather_location field.
//
// Any <input data-location-typeahead> on the page gets a dropdown of
// city candidates as the user types. Calls /api/locations/search?q=…
// (which proxies OpenWeatherMap geocoding), debounced.
//
// Selecting a result writes "City,CC" into the input so the OWM
// weather endpoint can resolve it unambiguously. We don't auto-
// submit the form — the user still has to hit Save / Continue;
// they may want to also edit other fields on the page first.

(function () {
  const inputs = document.querySelectorAll('input[data-location-typeahead]');
  inputs.forEach(attach);

  function attach(input) {
    let panel = null;
    let cursor = -1;          // keyboard-nav index
    let lastQuery = '';
    let debounceTimer = null;

    input.setAttribute('autocomplete', 'off');
    input.setAttribute('spellcheck', 'false');

    input.addEventListener('input', () => {
      const q = input.value.trim();
      clearTimeout(debounceTimer);
      if (q.length < 2) {
        closePanel();
        return;
      }
      debounceTimer = setTimeout(() => fetchAndRender(q), 180);
    });

    input.addEventListener('keydown', (evt) => {
      if (!panel) return;
      const items = panel.querySelectorAll('.loc-typeahead__item');
      if (!items.length) return;
      if (evt.key === 'ArrowDown') {
        evt.preventDefault();
        cursor = Math.min(cursor + 1, items.length - 1);
        highlight(items);
      } else if (evt.key === 'ArrowUp') {
        evt.preventDefault();
        cursor = Math.max(cursor - 1, 0);
        highlight(items);
      } else if (evt.key === 'Enter') {
        if (cursor >= 0 && cursor < items.length) {
          evt.preventDefault();
          choose(items[cursor]);
        }
      } else if (evt.key === 'Escape') {
        closePanel();
      }
    });

    document.addEventListener('click', (evt) => {
      if (!panel) return;
      if (input.contains(evt.target) || panel.contains(evt.target)) return;
      closePanel();
    });

    function highlight(items) {
      items.forEach((el, i) => el.classList.toggle('loc-typeahead__item--active', i === cursor));
    }

    async function fetchAndRender(q) {
      if (q === lastQuery) return;
      lastQuery = q;
      let data;
      try {
        const r = await fetch('/api/locations/search?q=' + encodeURIComponent(q));
        if (!r.ok) { closePanel(); return; }
        data = await r.json();
      } catch (_) {
        closePanel();
        return;
      }
      // Race-condition guard — by the time fetch returned, the user
      // may have typed more. Drop the response if the query changed.
      if (input.value.trim() !== q) return;
      render(data.results || []);
    }

    function render(results) {
      if (!results.length) { closePanel(); return; }
      if (!panel) {
        panel = document.createElement('div');
        panel.className = 'loc-typeahead';
        input.parentElement.style.position = 'relative';
        input.parentElement.appendChild(panel);
      }
      panel.innerHTML = '';
      cursor = -1;
      results.forEach((r) => {
        const item = document.createElement('button');
        item.type = 'button';                   // never let it submit the form
        item.className = 'loc-typeahead__item';
        item.dataset.value = r.value || r.name;
        item.textContent = r.label;
        item.addEventListener('mouseenter', () => {
          cursor = Array.from(panel.children).indexOf(item);
          highlight(panel.querySelectorAll('.loc-typeahead__item'));
        });
        item.addEventListener('click', () => choose(item));
        panel.appendChild(item);
      });
    }

    function choose(item) {
      input.value = item.dataset.value;
      closePanel();
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function closePanel() {
      if (panel) {
        panel.remove();
        panel = null;
      }
      cursor = -1;
    }
  }
})();
