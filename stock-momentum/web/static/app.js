// No framework. Two jobs: the equity crosshair, and running a bot action.
(function () {
  "use strict";

  /* ---------- crosshair on the equity chart ---------- */
  function crosshair() {
    var svg = document.querySelector('svg[data-chart="equity"]');
    var tip = document.getElementById("eqtip");
    if (!svg || !tip) return;
    var cross = svg.querySelector(".cross");
    var line = svg.querySelector(".crossline");
    var dot = svg.querySelector(".crossdot");
    var wrap = svg.parentElement;

    svg.addEventListener("pointermove", function (ev) {
      var t = ev.target;
      if (!t || t.tagName !== "rect" || !t.hasAttribute("data-i")) return;
      var x = +t.getAttribute("data-x"), y = +t.getAttribute("data-y");
      line.setAttribute("x1", x); line.setAttribute("x2", x);
      dot.setAttribute("cx", x); dot.setAttribute("cy", y);
      cross.classList.add("on");

      var pc = t.getAttribute("data-p") || "";
      var cls = pc.charAt(0) === "-" ? "down" : "up";
      tip.innerHTML =
        '<div class="d">' + t.getAttribute("data-d") + "</div>" +
        '<div class="val">' + t.getAttribute("data-v") + "</div>" +
        '<div class="pc ' + cls + '">' + pc + "</div>";
      tip.classList.add("on");

      // The SVG scales to the panel, so translate viewBox x into real pixels.
      var box = svg.getBoundingClientRect();
      var vb = svg.viewBox.baseVal;
      var px = (x - vb.x) / vb.width * box.width;
      var w = tip.offsetWidth || 140;
      tip.style.left = Math.max(4, Math.min(px + 14, box.width - w - 4)) + "px";
      tip.style.top = "10px";
    });

    svg.addEventListener("pointerleave", function () {
      cross.classList.remove("on");
      tip.classList.remove("on");
    });
  }

  /* ---------- run a bot action ---------- */
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
    show("Running " + action + "…\nA price download can take up to a minute.");
    fetch("/api/action", {
      method: "POST",
      body: new URLSearchParams({ action: action, csrf: csrf }),
      credentials: "same-origin",
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

  crosshair();
})();
