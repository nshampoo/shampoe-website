// Theme toggle. Pages also run a one-line copy of applyStored() inline in <head> so the
// chosen theme is set before first paint (no flash of the wrong theme).
(function () {
  var KEY = "theme";
  var root = document.documentElement;

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function save(value) {
    try { localStorage.setItem(KEY, value); } catch (e) { /* private mode: still works for this page */ }
  }
  function current() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function label(button) {
    button.setAttribute("aria-label", current() === "dark" ? "Switch to light mode" : "Switch to dark mode");
  }

  var s = stored();
  if (s === "light" || s === "dark") root.setAttribute("data-theme", s);

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.querySelector(".theme-toggle");
    if (!button) return;
    label(button);
    button.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      save(next);
      label(button);
    });
  });
})();
