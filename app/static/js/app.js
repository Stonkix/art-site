(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  // ---------- Мобильное меню ----------
  const burger = $(".burger");
  const nav = $("#main-nav");
  burger?.addEventListener("click", () => {
    const open = nav.classList.toggle("is-open");
    burger.setAttribute("aria-expanded", String(open));
  });

  // ---------- Модалка заявки: [data-lead="kind"] + data-title / data-sub / data-painting ----------
  const dialog = $("#lead-dialog");
  const tpl = $("#lead-form-tpl");
  const defaultTitle = $("#lead-dialog-title")?.textContent;
  const defaultSub = $("#lead-dialog-sub")?.textContent;

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-lead]");
    if (!trigger || !dialog) return;
    const body = $("#lead-dialog-body");
    body.replaceChildren(tpl.content.cloneNode(true));
    const form = $("form", body);
    form.elements.kind.value = trigger.dataset.lead;
    if (trigger.dataset.painting) {
      form.insertAdjacentHTML("afterbegin", `<input type="hidden" name="painting_id" value="${Number(trigger.dataset.painting)}">`);
    }
    $("#lead-dialog-title").textContent = trigger.dataset.title || defaultTitle;
    $("#lead-dialog-sub").textContent = trigger.dataset.sub || defaultSub;
    window.htmx?.process(body);
    dialog.showModal();
    form.elements.name.focus();
  });

  $$("dialog").forEach((d) => {
    d.addEventListener("click", (e) => {
      if (e.target === d || e.target.classList.contains("lb-stage") || e.target.closest("[data-close]")) d.close();
    });
  });

  // ---------- Бюджет: «50000» → «50 000» ----------
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!el.classList?.contains("js-money")) return;
    const digits = el.value.replace(/\D/g, "").slice(0, 10);
    el.value = digits ? Number(digits).toLocaleString("ru-RU") : "";
  });

  // Чистый URL фильтров: без пустых параметров и пробелов в суммах
  document.addEventListener("htmx:configRequest", (e) => {
    const fd = e.detail.formData;
    if (!fd || e.detail.verb !== "get") return;
    for (const [key, value] of [...fd.entries()]) {
      if (value === "" || (key === "sort" && value === "new")) fd.delete(key);
      else if (key === "price_max") fd.set(key, String(value).replace(/\D/g, ""));
    }
  });

  // Фильтры на телефоне свёрнуты — кнопка в строке результатов
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-filters-toggle]")) $("#filters")?.classList.toggle("is-open");
  });

  // Жанры-чипсы: меняют жанр в форме фильтров, остальные фильтры сохраняются
  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip[data-genre]");
    const form = $("#filters");
    if (!chip || !form || !window.htmx) return;
    e.preventDefault();
    form.elements.genre.value = chip.dataset.genre;
    $$(".chip").forEach((c) => (c === chip ? c.setAttribute("aria-current", "true") : c.removeAttribute("aria-current")));
    form.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // ---------- Галерея картины ----------
  const gallery = $("[data-gallery]");
  const lightbox = $("#lightbox");
  if (gallery && lightbox) {
    const srcs = $$("img", $("template[data-gallery-src]", gallery).content).map((img) => ({ src: img.src, alt: img.alt }));
    const mainImg = $("#art-main-img");
    const mainBtn = $(".art-view", gallery);
    const lbImg = $(".lb-img", lightbox);
    let current = 0;

    // миниатюры переключают большое фото на странице
    $$("[data-show]", gallery).forEach((btn) => {
      btn.addEventListener("click", () => {
        current = Number(btn.dataset.show);
        mainImg.src = srcs[current].src;
        mainImg.removeAttribute("width");
        mainImg.removeAttribute("height");
        mainBtn.dataset.index = current;
        $$("[data-show]", gallery).forEach((b) => b.setAttribute("aria-current", String(b === btn)));
      });
    });

    const show = (i) => {
      current = (i + srcs.length) % srcs.length;
      lbImg.classList.remove("is-zoomed");
      lbImg.src = srcs[current].src;
      lbImg.alt = srcs[current].alt;
    };
    const single = srcs.length < 2;
    $$(".lb-nav", lightbox).forEach((b) => { b.hidden = single; });

    mainBtn.addEventListener("click", () => {
      show(Number(mainBtn.dataset.index || 0));
      lightbox.showModal();
    });
    $(".lb-prev", lightbox).addEventListener("click", () => show(current - 1));
    $(".lb-next", lightbox).addEventListener("click", () => show(current + 1));
    lightbox.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") show(current - 1);
      if (e.key === "ArrowRight") show(current + 1);
    });

    // увеличение: клик — приблизить в точке клика, движение мыши — рассматривать детали
    const setOrigin = (e) => {
      const r = lbImg.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * 100;
      const y = ((e.clientY - r.top) / r.height) * 100;
      lbImg.style.transformOrigin = `${Math.min(Math.max(x, 0), 100)}% ${Math.min(Math.max(y, 0), 100)}%`;
    };
    lbImg.addEventListener("click", (e) => {
      e.stopPropagation();
      setOrigin(e);
      lbImg.classList.toggle("is-zoomed");
    });
    lbImg.addEventListener("mousemove", (e) => {
      if (lbImg.classList.contains("is-zoomed")) setOrigin(e);
    });
    lightbox.addEventListener("close", () => lbImg.classList.remove("is-zoomed"));

    let touchX = null;
    lightbox.addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
    lightbox.addEventListener("touchend", (e) => {
      if (touchX === null || lbImg.classList.contains("is-zoomed")) return;
      const dx = e.changedTouches[0].clientX - touchX;
      if (Math.abs(dx) > 40 && !single) show(current + (dx < 0 ? 1 : -1));
      touchX = null;
    });
  }
})();
