// Форма картины в админке: drag-n-drop фото, порядок и удаление уже загруженных
(() => {
  "use strict";

  // ---------- Drag-n-drop фото ----------
  const input = document.getElementById("photos_upload");
  if (input) {
    const ACCEPT = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"];
    // HEIC с iPhone: на Windows браузер часто не знает тип файла, поэтому смотрим и на расширение
    const isHeic = (f) => /\.(heic|heif)$/i.test(f.name) || /image\/hei[cf]/.test(f.type);
    const isAccepted = (f) => ACCEPT.includes(f.type) || isHeic(f);
    const picked = new DataTransfer(); // накапливаем файлы из нескольких перетаскиваний
    const existing = document.getElementById("existing-photos");

    const zone = document.createElement("div");
    zone.className = "dropzone";
    zone.tabIndex = 0;
    zone.innerHTML = `
      ${existing ? `<div class="dz-existing"><div class="dz-caption">Загруженные фото: перетащите, чтобы поменять порядок (первое — главное), × — удалить. Изменения применятся после «Сохранить».</div><div class="dz-grid">${existing.innerHTML}</div></div>` : ""}
      <div class="dz-hint">
        <strong>Перетащите фото сюда</strong> или нажмите, чтобы выбрать
        <small>JPG, PNG, WebP, HEIC · можно сразу несколько · сожмутся автоматически</small>
      </div>
      <div class="dz-grid dz-new"></div>`;
    input.hidden = true;
    input.after(zone);
    const grid = zone.querySelector(".dz-new");

    // --- уже загруженные фото: порядок перетаскиванием и удаление ---
    const savedGrid = zone.querySelector(".dz-existing .dz-grid");
    let dragged = null;
    if (savedGrid) {
      const hidden = (name) => {
        const el = Object.assign(document.createElement("input"), { type: "hidden", name });
        zone.append(el);
        return el;
      };
      const orderInput = hidden("photo_order");
      const deleteInput = hidden("photo_delete");
      const syncSaved = () => {
        const items = [...savedGrid.querySelectorAll("[data-id]")];
        orderInput.value = items.map((el) => el.dataset.id).join(",");
        deleteInput.value = items.filter((el) => el.classList.contains("is-deleted")).map((el) => el.dataset.id).join(",");
      };
      savedGrid.addEventListener("click", (e) => {
        const btn = e.target.closest(".dz-remove");
        if (!btn) return;
        e.stopPropagation();
        const item = btn.closest("[data-id]");
        const deleted = item.classList.toggle("is-deleted");
        btn.textContent = deleted ? "↺" : "×";
        btn.title = deleted ? "Вернуть" : "Удалить фото";
        syncSaved();
      });
      savedGrid.addEventListener("dragstart", (e) => {
        dragged = e.target.closest("[data-id]");
        if (!dragged) return;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", dragged.dataset.id);
        dragged.classList.add("is-dragging");
      });
      savedGrid.addEventListener("dragover", (e) => {
        if (!dragged) return;
        e.preventDefault();
        e.stopPropagation();
        const over = e.target.closest("[data-id]");
        if (!over || over === dragged) return;
        const r = over.getBoundingClientRect();
        over[e.clientX > r.left + r.width / 2 ? "after" : "before"](dragged);
      });
      savedGrid.addEventListener("drop", (e) => {
        if (!dragged) return;
        e.preventDefault();
        e.stopPropagation();
      });
      savedGrid.addEventListener("dragend", () => {
        dragged?.classList.remove("is-dragging");
        dragged = null;
        syncSaved();
      });
      syncSaved();
    }

    const render = () => {
      grid.replaceChildren();
      [...picked.files].forEach((file, i) => {
        const item = document.createElement("div");
        item.className = "dz-item";
        let img;
        if (isHeic(file)) {
          // браузеры (кроме Safari) не показывают HEIC — вместо превью плитка с именем, сервер всё сконвертирует
          img = document.createElement("div");
          img.className = "dz-heic";
          img.textContent = file.name;
        } else {
          img = document.createElement("img");
          img.src = URL.createObjectURL(file);
          img.onload = () => URL.revokeObjectURL(img.src);
          img.alt = file.name;
        }
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "dz-remove";
        remove.title = "Убрать";
        remove.textContent = "×";
        remove.addEventListener("click", (e) => {
          e.stopPropagation();
          picked.items.remove(i);
          sync();
        });
        item.append(img, remove);
        grid.append(item);
      });
      zone.classList.toggle("has-files", picked.files.length > 0);
    };
    const sync = () => {
      input.files = picked.files;
      render();
    };
    const add = (files) => {
      const skipped = [];
      for (const f of files) {
        if (!isAccepted(f)) { skipped.push(f.name); continue; }
        const dup = [...picked.files].some((x) => x.name === f.name && x.size === f.size);
        if (!dup) picked.items.add(f);
      }
      if (skipped.length) alert(`Пропущены (формат не поддерживается): ${skipped.join(", ")}`);
      sync();
    };

    zone.addEventListener("click", (e) => {
      if (!e.target.closest(".dz-existing, .dz-remove")) input.click();
    });
    zone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
    input.addEventListener("change", () => add(input.files));
    ["dragenter", "dragover"].forEach((ev) =>
      zone.addEventListener(ev, (e) => { e.preventDefault(); if (!dragged) zone.classList.add("is-over"); }));
    ["dragleave", "drop"].forEach((ev) =>
      zone.addEventListener(ev, () => zone.classList.remove("is-over")));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      if (dragged) return; // это была перестановка загруженных фото, а не новые файлы
      add(e.dataTransfer.files);
    });
    // файл, брошенный мимо зоны, не должен открываться во вкладке вместо формы
    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => e.preventDefault());
  }
})();
