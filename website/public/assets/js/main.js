/* Loudstudio — small progressive enhancements. The site works without this file. */
(function () {
  "use strict";

  var root = document.documentElement;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.classList.add("js");

  /* ---------- Header: solid after scrolling, hidden while scrolling down ---------- */
  var header = document.querySelector(".site-header");
  var lastY = window.scrollY;
  var ticking = false;

  function onScroll() {
    var y = window.scrollY;
    if (header) {
      header.classList.toggle("is-scrolled", y > 24);
      var hide = y > lastY && y > 320 && !root.classList.contains("menu-open");
      header.classList.toggle("is-hidden", hide);
    }
    lastY = y;
    ticking = false;
  }
  window.addEventListener("scroll", function () {
    if (!ticking) {
      window.requestAnimationFrame(onScroll);
      ticking = true;
    }
  }, { passive: true });
  onScroll();

  /* ---------- Mobile menu ---------- */
  var toggle = document.querySelector(".menu-toggle");
  var menu = document.getElementById("mobile-menu");

  function setMenu(open) {
    root.classList.toggle("menu-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.querySelector(".menu-toggle__label").textContent = open ? toggle.dataset.close : toggle.dataset.open;
    menu.toggleAttribute("inert", !open);
    if (open) {
      var first = menu.querySelector("a");
      if (first) first.focus();
    }
  }
  if (toggle && menu) {
    menu.setAttribute("inert", "");
    toggle.addEventListener("click", function () {
      setMenu(toggle.getAttribute("aria-expanded") !== "true");
    });
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a")) setMenu(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && root.classList.contains("menu-open")) {
        setMenu(false);
        toggle.focus();
      }
    });
    window.matchMedia("(min-width: 960px)").addEventListener("change", function (mq) {
      if (mq.matches) setMenu(false);
    });
  }

  /* ---------- Hero level meter (decorative) ---------- */
  var meter = document.querySelector(".meter");
  if (meter && !reduceMotion) {
    var bars = window.innerWidth < 700 ? 28 : 64;
    var frag = document.createDocumentFragment();
    for (var i = 0; i < bars; i++) {
      var s = document.createElement("span");
      var x = i / bars;
      var h = 0.18 + 0.62 * Math.pow(Math.sin(Math.PI * x), 1.6) * (0.55 + 0.45 * Math.abs(Math.sin(i * 1.7)));
      s.style.setProperty("--h", h.toFixed(3));
      s.style.setProperty("--d", (-(i * 0.137) % 2.6).toFixed(2) + "s");
      frag.appendChild(s);
    }
    meter.appendChild(frag);
  }

  /* ---------- Reveal on scroll ---------- */
  var reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add("is-visible"); });
  }

  window.addEventListener("load", function () { root.classList.add("is-loaded"); });
  // Fonts or images can delay "load"; never keep the headline hidden for long.
  window.setTimeout(function () { root.classList.add("is-loaded"); }, 1200);

  /* ---------- Map: load the embed only when the visitor asks ---------- */
  document.querySelectorAll("[data-map-load]").forEach(function (button) {
    button.addEventListener("click", function () {
      var map = button.closest(".map");
      var iframe = document.createElement("iframe");
      iframe.src = map.dataset.mapSrc;
      iframe.title = map.dataset.mapTitle || "Mapa";
      iframe.loading = "lazy";
      iframe.referrerPolicy = "no-referrer-when-downgrade";
      map.appendChild(iframe);
      var placeholder = map.querySelector(".map__placeholder");
      if (placeholder) placeholder.remove();
    });
  });

  /* ---------- Contact form ---------- */
  var params = new URLSearchParams(window.location.search);

  document.querySelectorAll("form[data-contact-form]").forEach(function (form) {
    var subject = form.querySelector("[name=assunto]");
    if (subject && params.get("assunto")) {
      var wanted = params.get("assunto");
      Array.prototype.forEach.call(subject.options, function (opt) {
        if (opt.value === wanted) subject.value = wanted;
      });
    }

    // Seconds spent on the page before sending (measured here, so clocks do not matter)
    var elapsed = form.querySelector("[name=t]");
    var openedAt = Date.now();

    var status = form.querySelector(".form__status");
    var messages = {
      sending: form.dataset.msgSending,
      ok: form.dataset.msgOk,
      error: form.dataset.msgError
    };

    form.addEventListener("submit", function (e) {
      if (elapsed) elapsed.value = String(Math.round((Date.now() - openedAt) / 1000));
      if (!window.fetch || !window.FormData) return;
      e.preventDefault();
      if (!form.reportValidity()) return;

      var button = form.querySelector("[type=submit]");
      form.setAttribute("aria-busy", "true");
      button.disabled = true;
      status.className = "form__status";
      status.textContent = messages.sending;

      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "Accept": "application/json" }
      })
        .then(function (res) {
          return res.json().catch(function () { return { ok: false }; }).then(function (data) {
            return { ok: res.ok && data.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.ok) {
            form.reset();
            openedAt = Date.now();
            status.className = "form__status form__status--ok";
            status.textContent = messages.ok;
          } else {
            status.className = "form__status form__status--error";
            status.textContent = (result.data && result.data.message) || messages.error;
          }
        })
        .catch(function () {
          status.className = "form__status form__status--error";
          status.textContent = messages.error;
        })
        .then(function () {
          form.removeAttribute("aria-busy");
          button.disabled = false;
          status.focus();
        });
    });
  });

  /* Result of a form sent without JavaScript (contacto.php redirects back here) */
  var sent = params.get("enviado");
  if (sent) {
    var notice = document.querySelector('.notice[data-result="' + (sent === "1" ? "ok" : "error") + '"]');
    if (notice) {
      notice.hidden = false;
      notice.focus();
    }
  }

  /* ---------- Footer year ---------- */
  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });
})();
