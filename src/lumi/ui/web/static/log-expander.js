// Collapsible audit/activity rows.
//
// Each summary row has a sibling `.row-detail` row beneath it carrying
// the full input + result text. Clicking the row toggles the detail
// row's open state. The summary text stays one-line-clipped so the
// table never overflows its container.
//
// Event delegation off document so HTMX swaps that refresh
// `#log-rows` automatically get the binding without re-attaching.

(function () {
  document.addEventListener('click', function (evt) {
    const target = evt.target;
    // Ignore clicks on links / buttons inside the row — those should
    // do their own thing, not toggle the panel.
    if (target.closest('a, button.btn, form')) {
      // ...but the chevron itself IS a button. Let it through.
      if (!target.closest('.row-expand')) return;
    }
    const row = target.closest('tr.row-summary');
    if (!row) return;

    const detailId = row.dataset.detailFor;
    if (!detailId) return;
    const detail = document.getElementById(detailId);
    if (!detail) return;

    const open = detail.classList.toggle('row-detail--open');
    row.classList.toggle('row-expanded', open);
  });
})();
