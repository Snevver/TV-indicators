// No framework. Two jobs: run an action and show its output.
(function () {
  "use strict";
  var out = document.getElementById("out");

  function show(text) {
    if (!out) return;
    out.hidden = false;
    out.textContent = text;
    out.scrollTop = 0;
  }

  function run(button, action, csrf) {
    var label = button.textContent;
    button.disabled = true;
    button.textContent = "Running…";
    show("Running " + action + "…\nThe price download can take up to a minute.");
    var body = new URLSearchParams({ action: action, csrf: csrf });
    fetch("/api/action", {
      method: "POST", body: body, credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" }
    })
      .then(function (r) {
        if (r.status === 401) { window.location = "/login"; return null; }
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        var text = (d.out || "") + (d.err ? "\n" + d.err : "");
        show(text.trim() || (d.ok ? "Done. No output." : "Failed with no output."));
        if (d.ok && (action === "refresh" || action === "sync")) {
          setTimeout(function () { window.location.reload(); }, 900);
        }
      })
      .catch(function (e) { show("Could not reach the dashboard: " + e); })
      .finally(function () {
        button.disabled = false;
        button.textContent = label;
      });
  }

  var panel = document.querySelector(".actions");
  if (panel) {
    panel.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-action]");
      if (b) run(b, b.getAttribute("data-action"), panel.getAttribute("data-csrf"));
    });
  }

  var refresh = document.getElementById("refresh");
  if (refresh) {
    refresh.addEventListener("click", function () {
      run(refresh, "refresh", refresh.getAttribute("data-csrf"));
    });
  }
})();
