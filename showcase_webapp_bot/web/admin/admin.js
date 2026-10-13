const state = {
  cars: [],
  leads: [],
  leadScope: "active",
  scope: "active",
  pendingPhotos: [],
  removedPhotoIds: new Set(),
  selectedId: null,
  role: document.querySelector(".admin-shell").dataset.role,
  csrf: document.querySelector('meta[name="csrf-token"]').content,
};

const elements = {
  shell: document.querySelector(".admin-shell"),
  leadsCount: document.querySelector("#leads-count"),
  list: document.querySelector("#admin-car-list"),
  search: document.querySelector("#admin-search"),
  empty: document.querySelector("#editor-empty"),
  form: document.querySelector("#car-form"),
  title: document.querySelector("#editor-title"),
  kicker: document.querySelector("#editor-kicker"),
  deleteCar: document.querySelector("#delete-car"),
  photosSection: document.querySelector("#photos-section"),
  photoList: document.querySelector("#photo-list"),
  photoUpload: document.querySelector("#photo-upload"),
  usersDialog: document.querySelector("#users-dialog"),
  leadsDialog: document.querySelector("#leads-dialog"),
  leadsList: document.querySelector("#leads-list"),
  leadsSummary: document.querySelector("#leads-summary"),
  leadsSearch: document.querySelector("#leads-search"),
  leadsStatus: document.querySelector("#leads-status"),
  actionsDialog: document.querySelector("#actions-dialog"),
  actionsList: document.querySelector("#actions-list"),
  summary: document.querySelector("#admin-summary"),
  photosHint: document.querySelector("#photos-hint"),
  toggleSold: document.querySelector("#toggle-sold"),
  usersList: document.querySelector("#users-list"),
  userForm: document.querySelector("#user-form"),
  toast: document.querySelector("#admin-toast"),
};

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

let toastTimer;
function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");
  toastTimer = setTimeout(() => elements.toast.classList.remove("is-visible"), 3000);
}

// Демо-админка (/admin/demo): запросы не уходят на сервер, см. demoApi в конце файла.
const isDemo = elements.shell.dataset.demo === "1";

async function api(url, options = {}) {
  if (isDemo) return demoApi(url, options);
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.method && options.method !== "GET") headers.set("X-CSRF-Token", state.csrf);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    window.location.assign("/admin/login");
    throw new Error("Сессия завершена");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || "Не удалось выполнить действие");
  }
  return response.status === 204 ? null : response.json();
}

function currentCar() {
  return state.cars.find((car) => car.id === state.selectedId);
}

function visibleCars() {
  const query = elements.search.value.trim().toLowerCase();
  return state.cars
    .filter((car) => (state.scope === "sold" ? car.is_sold : !car.is_sold))
    .filter((car) => `${car.brand} ${car.model}`.toLowerCase().includes(query));
}

function renderList() {
  const cars = visibleCars();
  elements.list.replaceChildren(...cars.map((car) => {
    const button = document.createElement("button");
    button.type = "button";
    button.draggable = state.scope === "active";
    button.dataset.carId = car.id;
    button.className = `admin-car ${car.id === state.selectedId ? "is-active" : ""}`;
    const image = document.createElement("img");
    image.src = car.images[0]?.url || "";
    image.alt = "";
    const text = document.createElement("span");
    const title = document.createElement("b");
    title.textContent = `${car.brand} ${car.model}`;
    const meta = document.createElement("small");
    meta.textContent = car.is_sold
      ? `${car.year} · продан`
      : `${car.year} · ${locationName(car.location)}`;
    text.append(title, meta);
    const visibility = document.createElement("i");
    visibility.className = `visibility ${car.is_visible ? "is-visible" : ""}`;
    button.append(image, text, visibility);
    button.addEventListener("click", () => selectCar(car.id));
    button.addEventListener("dragstart", () => { dragCarId = car.id; });
    button.addEventListener("dragover", (event) => event.preventDefault());
    button.addEventListener("drop", (event) => {
      event.preventDefault();
      reorderCars(dragCarId, car.id);
    });
    return button;
  }));
}

// Перетаскивание — необязательная замена полю «Порядок»: оно остаётся на месте.
let dragCarId = null;

async function reorderCars(fromId, toId) {
  if (!fromId || fromId === toId) return;
  const order = visibleCars().map((car) => car.id);
  const from = order.indexOf(fromId);
  const to = order.indexOf(toId);
  if (from < 0 || to < 0) return;
  order.splice(to, 0, ...order.splice(from, 1));
  try {
    for (const [index, carId] of order.entries()) {
      const car = state.cars.find((item) => item.id === carId);
      if (!car || car.sort_order === index) continue;
      await api(`/api/admin/cars/${encodeURIComponent(carId)}`, {
        method: "PUT",
        body: JSON.stringify({ ...car, sort_order: index }),
      });
    }
    await loadCars();
    showToast("Порядок обновлён");
  } catch (error) { showToast(error.message); }
}

function formData() {
  const data = Object.fromEntries(new FormData(elements.form));
  return {
    ...data,
    year: Number(data.year),
    price: Number(data.price),
    mileage: Number(data.mileage),
    sort_order: Number(data.sort_order),
    is_visible: elements.form.elements.is_visible.checked,
  };
}

// Внутри Telegram у мини-приложения своя кнопка «Назад» в шапке (и системная
// «назад» на Android): она закрывает окно или карточку, а не всю админку.
const telegram = window.Telegram?.WebApp;
// После перехода с /admin/tg данные запуска Telegram берёт из sessionStorage.
const insideTelegram = Boolean(telegram?.initData) || (telegram?.platform ?? "unknown") !== "unknown";
const phoneLayout = window.matchMedia("(max-width: 850px)");
let listScrollY = 0;

function openDialog() {
  return [...document.querySelectorAll("dialog")].find((dialog) => dialog.open);
}

function editorIsScreen() {
  return phoneLayout.matches && !elements.form.hidden;
}

function goBack() {
  const dialog = openDialog();
  if (dialog) dialog.close();
  else if (editorIsScreen()) closeEditor();
}

// Подсказка нужна только на стартовом экране: карточка не открыта,
// выбрана вкладка «В продаже» и не открыто ни одно окно. Здесь же решаем,
// нужна ли кнопка «Назад» Telegram: все переходы между экранами идут сюда.
function updateEmptyHint() {
  elements.empty.hidden = !elements.form.hidden || state.scope !== "active" || Boolean(openDialog());
  if (!insideTelegram) return;
  if (openDialog() || editorIsScreen()) telegram.BackButton.show();
  else telegram.BackButton.hide();
}

// На телефоне карточка открывается отдельным экраном вместо списка.
function showEditor() {
  if (elements.form.hidden) listScrollY = window.scrollY;
  elements.form.hidden = false;
  elements.shell.classList.add("is-editing");
  if (phoneLayout.matches) window.scrollTo(0, 0);
  updateEmptyHint();
}

function closeEditor() {
  state.selectedId = null;
  discardPhotoChanges();
  elements.form.hidden = true;
  elements.shell.classList.remove("is-editing");
  renderList();
  updateEmptyHint();
  if (phoneLayout.matches) window.scrollTo(0, listScrollY);
}

function newCar() {
  state.selectedId = null;
  showEditor();
  elements.form.reset();
  elements.form.elements.original_id.value = "";
  elements.form.elements.sort_order.value = "0";
  elements.form.elements.is_visible.checked = true;
  elements.form.elements.id.disabled = false;
  elements.title.textContent = "Новый автомобиль";
  elements.kicker.textContent = "Создание карточки";
  elements.photosSection.hidden = false;
  discardPhotoChanges();
  renderPhotos();
  elements.deleteCar.hidden = true;
  elements.toggleSold.hidden = true;
  renderList();
  // На телефоне клавиатура сразу закрыла бы полкарточки.
  if (!phoneLayout.matches) elements.form.elements.id.focus();
}

function selectCar(carId) {
  const car = state.cars.find((item) => item.id === carId);
  if (!car) return;
  state.selectedId = carId;
  showEditor();
  elements.form.reset();
  Object.entries(car).forEach(([key, value]) => {
    if (elements.form.elements[key] && key !== "is_visible") elements.form.elements[key].value = value;
  });
  elements.form.elements.original_id.value = car.id;
  elements.form.elements.id.value = car.id;
  elements.form.elements.id.disabled = true;
  elements.form.elements.is_visible.checked = car.is_visible;
  elements.title.textContent = `${car.brand} ${car.model}`;
  elements.kicker.textContent = locationName(car.location);
  elements.photosSection.hidden = false;
  discardPhotoChanges();
  elements.deleteCar.hidden = !["owner", "developer"].includes(state.role);
  elements.toggleSold.hidden = false;
  elements.toggleSold.textContent = car.is_sold ? "Вернуть в продажу" : "Продано";
  renderPhotos();
  renderList();
}

// Правки фотографий копятся в карточке и уходят на сервер только по
// «Сохранить»: до этого каталог показывает прежний набор. Добавленные файлы
// показываем из памяти браузера, удалённые просто прячем.
function discardPhotoChanges() {
  state.pendingPhotos.forEach((item) => URL.revokeObjectURL(item.url));
  state.pendingPhotos = [];
  state.removedPhotoIds.clear();
}

function addPendingPhotos(files) {
  state.pendingPhotos.push(...files.map((file) => ({ file, url: URL.createObjectURL(file) })));
  renderPhotos();
}

function renderPhotos() {
  const car = currentCar();
  const saved = (car?.images || [])
    .filter((photo) => !state.removedPhotoIds.has(photo.id))
    .map((photo) => ({
      src: photo.url,
      alt: photo.alt_text || `${car.brand} ${car.model}`,
      remove: () => state.removedPhotoIds.add(photo.id),
    }));
  const pending = state.pendingPhotos.map((item) => ({
    src: item.url,
    alt: item.file.name,
    remove: () => {
      URL.revokeObjectURL(item.url);
      state.pendingPhotos = state.pendingPhotos.filter((other) => other !== item);
    },
  }));
  elements.photoList.replaceChildren(...[...saved, ...pending].map((photo, index) => {
    const card = document.createElement("div");
    card.className = "photo";
    const image = document.createElement("img");
    image.src = photo.src;
    image.alt = photo.alt;
    const order = document.createElement("span");
    order.className = "photo-order";
    order.textContent = `Фото ${index + 1}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", "Убрать фотографию");
    remove.addEventListener("click", () => {
      photo.remove();
      renderPhotos();
    });
    card.append(image, order, remove);
    return card;
  }));
  const changed = state.pendingPhotos.length > 0 || state.removedPhotoIds.size > 0;
  elements.photosHint.hidden = Boolean(car) && !changed;
  if (car) {
    elements.photosHint.textContent = "Изменения в фотографиях применятся после «Сохранить».";
  } else {
    elements.photosHint.textContent = state.pendingPhotos.length
      ? "Фотографии сохранятся вместе с карточкой."
      : "Добавьте фотографии — они сохранятся вместе с карточкой.";
  }
}

async function loadCars(selectId = state.selectedId) {
  const data = await api("/api/admin/cars");
  state.cars = data.cars;
  renderList();
  if (selectId && state.cars.some((car) => car.id === selectId)) selectCar(selectId);
}

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!elements.form.reportValidity()) return;
  const data = formData();
  const originalId = elements.form.elements.original_id.value;
  // Публикация видна клиентам сразу, поэтому спрашиваем отдельно.
  const carName = `«${data.brand} ${data.model}»`;
  const question = originalId
    ? `Применить изменения и выставить ${carName} в каталог?`
    : `Выставить ${carName} в каталог?`;
  if (data.is_visible && !confirm(question)) return;
  try {
    const result = await api(
      originalId ? `/api/admin/cars/${encodeURIComponent(originalId)}` : "/api/admin/cars",
      { method: originalId ? "PUT" : "POST", body: JSON.stringify(data) },
    );
    const carId = result.car.id;
    let photoError = null;
    try {
      for (const photoId of state.removedPhotoIds) {
        await api(`/api/admin/images/${photoId}`, { method: "DELETE" });
      }
      if (state.pendingPhotos.length) {
        await uploadPhotos(carId, state.pendingPhotos.map((item) => item.file));
      }
    } catch (error) { photoError = error; }
    // Карточка уже создана: перечитываем её даже при ошибке с фото,
    // иначе повторное «Сохранить» попытается создать её второй раз.
    await loadCars(carId);
    showToast(photoError
      ? `Карточка сохранена, но фото не обновились: ${photoError.message}`
      : "Карточка сохранена");
  } catch (error) { showToast(error.message); }
});

elements.deleteCar.addEventListener("click", async () => {
  const car = currentCar();
  if (!car || !confirm(`Удалить ${car.brand} ${car.model} без возможности восстановления?`)) return;
  try {
    await api(`/api/admin/cars/${encodeURIComponent(car.id)}`, { method: "DELETE" });
    closeEditor();
    await loadCars();
    showToast("Автомобиль удалён");
  } catch (error) { showToast(error.message); }
});

// Сжимаем в браузере: Pillow на сервере тянуть ради этого не хочется,
// а исходники с телефона весят по 5-8 МБ и тормозят витрину.
const PHOTO_MAX_SIDE = 1600;

async function compressPhoto(file) {
  if (!file.type.startsWith("image/")) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size < 1_200_000) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.82));
    if (!blob || blob.size >= file.size) return file;
    const name = `${file.name.replace(/\.[^.]+$/, "")}.jpg`;
    return new File([blob], name, { type: "image/jpeg" });
  } catch (_error) {
    return file;
  }
}

async function uploadPhotos(carId, files) {
  const data = new FormData();
  for (const file of files) data.append("image", await compressPhoto(file));
  await api(`/api/admin/cars/${encodeURIComponent(carId)}/images`, {
    method: "POST",
    body: data,
  });
}

elements.photoUpload.addEventListener("change", () => {
  const files = [...elements.photoUpload.files];
  elements.photoUpload.value = "";
  if (files.length) addPendingPhotos(files);
});

elements.toggleSold.addEventListener("click", async () => {
  const car = currentCar();
  if (!car) return;
  const sold = !car.is_sold;
  if (sold && !confirm(`Отметить «${car.brand} ${car.model}» проданным? Из каталога он исчезнет.`)) return;
  try {
    await api(`/api/admin/cars/${encodeURIComponent(car.id)}/sold`, {
      method: "POST",
      body: JSON.stringify({ sold }),
    });
    await loadCars(car.id);
    showToast(sold ? "Автомобиль в архиве" : "Автомобиль вернулся в каталог");
  } catch (error) { showToast(error.message); }
});

document.querySelectorAll("[data-scope]").forEach((button) => {
  button.addEventListener("click", () => {
    state.scope = button.dataset.scope;
    document.querySelectorAll("[data-scope]").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.scope === state.scope);
    });
    renderList();
    updateEmptyHint();
  });
});

async function loadSummary() {
  try {
    const data = await api("/api/admin/summary");
    elements.summary.innerHTML = `
      <div><b>${data.cars}</b><span>в каталоге</span></div>
      <div><b>${data.leads_week}</b><span>заявок за неделю</span></div>
      <div class="${data.leads_new ? "is-alert" : ""}"><b>${data.leads_new}</b><span>без ответа</span></div>
      <div><b>${data.sold}</b><span>в архиве</span></div>
    `;
    elements.leadsCount.textContent = data.leads_new;
    elements.leadsCount.hidden = !data.leads_new;
  } catch (_error) {
    elements.summary.hidden = true;
  }
}

const ROLE_LABELS = { manager: "Менеджер", owner: "Владелец", developer: "Разработчик" };

function roleBadge(role) {
  const badge = document.createElement("b");
  badge.className = `role-badge role-badge--${role}`;
  badge.textContent = ROLE_LABELS[role] || role;
  return badge;
}

async function loadUsers() {
  const data = await api("/api/admin/users");
  const currentId = (await api("/api/admin/session")).user.id;
  elements.usersList.replaceChildren(...data.users.map((user) => {
    const row = document.createElement("div");
    row.className = `user-row ${user.is_active ? "" : "is-disabled"}`;
    const text = document.createElement("span");
    text.className = "user-row__text";
    const name = document.createElement("b");
    name.textContent = user.username;
    const status = document.createElement("small");
    status.textContent = user.is_active ? "Доступ активен" : "Доступ отключён";
    text.append(name, status);
    row.append(text);
    // Где роль можно сменить списком, метка рядом с ним лишняя.
    if (!(user.can_manage && data.assignable_roles.length > 1)) row.append(roleBadge(user.role));

    // Кем распоряжаться, решает сервер: владелец — своими менеджерами,
    // разработчик — всеми. Остальные строки только для просмотра.
    if (!user.can_manage) {
      const note = document.createElement("small");
      note.className = "user-row__note";
      note.textContent = user.id === currentId ? "Это вы" : "Управляет разработчик";
      row.append(note);
      return row;
    }

    const update = async (changes, message) => {
      try {
        await api(`/api/admin/users/${user.id}`, {
          method: "PUT",
          body: JSON.stringify({ role: user.role, is_active: user.is_active, ...changes }),
        });
        await loadUsers();
        if (message) showToast(message);
      } catch (error) { showToast(error.message); }
    };
    const controls = document.createElement("span");
    controls.className = "user-row__controls";
    if (data.assignable_roles.length > 1) {
      const role = document.createElement("select");
      data.assignable_roles.forEach((value) => role.add(new Option(ROLE_LABELS[value], value)));
      role.value = user.role;
      role.addEventListener("change", () => update({ role: role.value }, "Роль изменена"));
      controls.append(role);
    }
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.textContent = user.is_active ? "Отключить" : "Включить";
    toggle.addEventListener("click", () => update({ is_active: !user.is_active }));
    const password = document.createElement("button");
    password.type = "button";
    password.textContent = "Пароль";
    password.addEventListener("click", () => {
      const value = prompt(`Новый пароль для «${user.username}», не менее 12 символов`);
      if (value) update({ password: value }, "Пароль изменён");
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Удалить";
    remove.addEventListener("click", async () => {
      if (!confirm(`Удалить учётную запись «${user.username}»?`)) return;
      try {
        await api(`/api/admin/users/${user.id}`, { method: "DELETE" });
        await loadUsers();
        showToast("Учётная запись удалена");
      } catch (error) { showToast(error.message); }
    });
    controls.append(toggle, password, remove);
    row.append(controls);
    return row;
  }));
}

document.querySelector("#new-car").addEventListener("click", newCar);
elements.search.addEventListener("input", renderList);
document.querySelector("#open-users")?.addEventListener("click", async () => {
  try {
    await loadUsers();
    elements.usersDialog.showModal();
    updateEmptyHint();
  } catch (error) { showToast(error.message); }
});
document.querySelector("[data-close-users]")?.addEventListener("click", () => elements.usersDialog.close());
elements.userForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!elements.userForm.reportValidity()) return;
  const data = Object.fromEntries(new FormData(elements.userForm));
  try {
    await api("/api/admin/users", { method: "POST", body: JSON.stringify(data) });
    elements.userForm.reset();
    await loadUsers();
    showToast("Пользователь создан");
  } catch (error) { showToast(error.message); }
});

const LEAD_TYPE_LABELS = { car: "Автомобиль", manager: "Помощь с выбором" };
const LEAD_SOURCE_LABELS = { telegram: "Telegram", site: "Витрина" };
const LEAD_STATUS_LABELS = {
  new: "Новая",
  in_work: "В работе",
  won: "Купили",
  lost: "Отказ",
};

function formatLeadDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "";
  return date.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

// Удалить заявку навсегда может владелец; менеджер убирает её в архив.
function canDeleteLeads() {
  return ["owner", "developer"].includes(state.role);
}

function leadRow(lead) {
  const article = document.createElement("article");
  article.className = `lead-row is-${lead.status}`;
  const contact = [lead.contact_username, lead.username && `@${lead.username}`]
    .filter(Boolean)
    .join(" · ");
  article.innerHTML = `
    <div class="lead-row__head">
      <b>${escapeHtml(lead.name)}</b>
      <span class="lead-row__source">${LEAD_SOURCE_LABELS[lead.source] || lead.source}</span>
      <time>${escapeHtml(formatLeadDate(lead.created_at))}</time>
    </div>
    <dl>
      <div><dt>Телефон</dt><dd><a href="tel:${escapeHtml(lead.phone)}">${escapeHtml(lead.phone)}</a></dd></div>
      <div><dt>Запрос</dt><dd>${LEAD_TYPE_LABELS[lead.lead_type] || lead.lead_type}</dd></div>
      <div><dt>Автомобиль</dt><dd>${escapeHtml(lead.car_interest)}</dd></div>
      <div><dt>Покупка</dt><dd>${escapeHtml(lead.purchase_method)}</dd></div>
      ${contact ? `<div><dt>Контакт</dt><dd>${escapeHtml(contact)}</dd></div>` : ""}
      ${lead.handled_by ? `<div><dt>Ведёт</dt><dd>${escapeHtml(lead.handled_by)}</dd></div>` : ""}
      ${lead.comment ? `<div class="lead-row__comment"><dt>Комментарий</dt><dd>${escapeHtml(lead.comment)}</dd></div>` : ""}
    </dl>
    <div class="lead-row__work">
      <select data-status>
        ${Object.entries(LEAD_STATUS_LABELS)
          .map(([value, label]) => `<option value="${value}" ${value === lead.status ? "selected" : ""}>${label}</option>`)
          .join("")}
      </select>
      <input data-note maxlength="1000" placeholder="Заметка: перезвонить, думает, купил" value="${escapeHtml(lead.note)}">
      <button type="button" data-save>Сохранить</button>
    </div>
    <div class="lead-row__manage">
      <button type="button" data-archive>${lead.is_archived ? "Вернуть из архива" : "В архив"}</button>
      ${canDeleteLeads() ? '<button type="button" class="danger" data-delete>Удалить</button>' : ""}
    </div>
  `;
  article.querySelector("[data-archive]").addEventListener("click", async () => {
    const archived = !lead.is_archived;
    try {
      await api(`/api/admin/leads/${lead.id}/archive`, {
        method: "POST",
        body: JSON.stringify({ archived }),
      });
      await loadLeads();
      loadSummary();
      showToast(archived ? "Заявка в архиве" : "Заявка вернулась в работу");
    } catch (error) { showToast(error.message); }
  });
  article.querySelector("[data-delete]")?.addEventListener("click", async () => {
    if (!confirm(`Удалить заявку «${lead.name}» навсегда? Вернуть её будет нельзя.`)) return;
    try {
      await api(`/api/admin/leads/${lead.id}`, { method: "DELETE" });
      await loadLeads();
      loadSummary();
      showToast("Заявка удалена");
    } catch (error) { showToast(error.message); }
  });
  article.querySelector("[data-save]").addEventListener("click", async () => {
    try {
      await api(`/api/admin/leads/${lead.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: article.querySelector("[data-status]").value,
          note: article.querySelector("[data-note]").value,
        }),
      });
      await loadLeads();
      loadSummary();
      showToast("Заявка обновлена");
    } catch (error) { showToast(error.message); }
  });
  return article;
}

function renderLeads() {
  const query = elements.leadsSearch.value.trim().toLowerCase();
  const status = elements.leadsStatus.value;
  const inScope = state.leads.filter((lead) => Boolean(lead.is_archived) === (state.leadScope === "archive"));
  const leads = inScope.filter((lead) => {
    const haystack = `${lead.name} ${lead.phone} ${lead.car_interest} ${lead.note}`.toLowerCase();
    return (!query || haystack.includes(query)) && (!status || lead.status === status);
  });
  elements.leadsList.replaceChildren(...leads.map(leadRow));
  if (leads.length) {
    elements.leadsSummary.textContent = `${leads.length} ${pluralLeads(leads.length)} из ${inScope.length}`;
  } else if (!inScope.length) {
    elements.leadsSummary.textContent = state.leadScope === "archive" ? "В архиве пусто" : "Активных заявок нет";
  } else {
    elements.leadsSummary.textContent = "Ничего не найдено";
  }
}

async function loadLeads() {
  const data = await api("/api/admin/leads");
  state.leads = data.leads || [];
  renderLeads();
}

function pluralLeads(count) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return "заявка";
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "заявки";
  return "заявок";
}

elements.leadsSearch?.addEventListener("input", renderLeads);
document.querySelectorAll("[data-lead-scope]").forEach((button) => {
  button.addEventListener("click", () => {
    state.leadScope = button.dataset.leadScope;
    document.querySelectorAll("[data-lead-scope]").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.leadScope === state.leadScope);
    });
    renderLeads();
  });
});
elements.leadsStatus?.addEventListener("change", renderLeads);

async function loadActions() {
  const data = await api("/api/admin/actions");
  elements.actionsList.replaceChildren(...(data.actions || []).map((entry) => {
    const row = document.createElement("div");
    row.className = "action-row";
    row.innerHTML = `
      <b>${escapeHtml(entry.username)}</b>
      <span>${escapeHtml(entry.action)}${entry.target ? ` · ${escapeHtml(entry.target)}` : ""}</span>
      <time>${escapeHtml(formatLeadDate(entry.created_at))}</time>
    `;
    return row;
  }));
}

document.querySelector("#open-actions")?.addEventListener("click", async () => {
  try {
    await loadActions();
    elements.actionsDialog.showModal();
    updateEmptyHint();
  } catch (error) { showToast(error.message); }
});
document.querySelector("[data-close-actions]")?.addEventListener("click", () => elements.actionsDialog.close());

document.querySelector("#open-leads")?.addEventListener("click", async () => {
  try {
    await loadLeads();
    elements.leadsDialog.showModal();
    updateEmptyHint();
  } catch (error) { showToast(error.message); }
});
document.querySelector("[data-close-leads]")?.addEventListener("click", () => elements.leadsDialog.close());

document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("close", updateEmptyHint));
document.querySelector("#editor-back").addEventListener("click", closeEditor);
phoneLayout.addEventListener("change", updateEmptyHint);

// В Telegram на телефоне у клавиатуры нет кнопки «Готово»: прячем её,
// когда нажали мимо поля или заметно пролистали страницу пальцем.
// Небольшой сдвиг пальца клавиатуру не трогает, чтобы она не пропадала случайно.
const KEYBOARD_HIDE_SWIPE_PX = 80;
const TAP_MAX_SHIFT_PX = 10;
let touchStart = null;

function hideKeyboard() {
  const field = document.activeElement;
  if (field?.matches?.("input, textarea")) field.blur();
}
document.addEventListener("touchstart", (event) => {
  touchStart = { y: event.touches[0].clientY, shift: 0 };
}, { passive: true });
document.addEventListener("touchmove", (event) => {
  if (!touchStart) return;
  touchStart.shift = Math.max(touchStart.shift, Math.abs(event.touches[0].clientY - touchStart.y));
  if (touchStart.shift >= KEYBOARD_HIDE_SWIPE_PX) hideKeyboard();
}, { passive: true });
document.addEventListener("touchend", (event) => {
  const tapped = touchStart && touchStart.shift < TAP_MAX_SHIFT_PX;
  touchStart = null;
  if (tapped && !event.target.closest?.("input, textarea, select, label")) hideKeyboard();
}, { passive: true });

if (insideTelegram) {
  telegram.ready();
  telegram.expand();
  telegram.BackButton.onClick(goBack);
  try { telegram.setHeaderColor("#17191d"); } catch (_error) { /* старые клиенты Telegram */ }
}

// --- Демо-админка ----------------------------------------------------------
// Песочница для потенциальных клиентов: все «серверные» действия выполняются
// здесь, в памяти вкладки. Машины берутся из публичного каталога (или из демо
// перегонщика по ?demo=<имя>), заявки и сотрудники — вымышленные. После
// обновления страницы всё возвращается к исходному, сервер ничего не получает.
const DEMO_OWNER = { id: 1, username: "owner", role: "owner" };
let demoReady = null;

function demoSlug() {
  const slug = new URLSearchParams(location.search).get("demo") || "";
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) ? slug : "";
}

// Песочница на сервере узнаёт хозяина по аккаунту Telegram (подписанные данные
// запуска) или по cookie браузера — поэтому каталог видит те же изменения.
function demoHeaders(extra = {}) {
  const headers = { Accept: "application/json", ...extra };
  const initData = window.Telegram?.WebApp?.initData;
  if (initData) headers["X-Telegram-Init-Data"] = initData;
  return headers;
}

async function demoFetchJson(url) {
  try {
    const response = await fetch(url, { headers: demoHeaders() });
    return response.ok ? await response.json() : null;
  } catch (_error) {
    return null;
  }
}

async function demoSend(url, method, body) {
  const isForm = body instanceof FormData;
  const response = await fetch(url, {
    method,
    headers: demoHeaders(isForm || body === undefined ? {} : { "Content-Type": "application/json" }),
    body: isForm || body === undefined ? body : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 410) demoShowEnded();
  if (!response.ok) throw new Error(payload.error || "Не удалось сохранить изменения демо");
  return payload;
}

// Сохраняет машины в песочницу: их же покажет демо-каталог этого человека.
async function demoPersist(data) {
  const slug = demoSlug();
  if (!slug) return;
  const cars = data.cars.map(({ images, ...car }) => ({
    ...car,
    images: (images || []).map(({ url, alt_text: altText }) => ({ url, alt_text: altText })),
  }));
  await demoSend(`/api/demos/${slug}/sandbox`, "PUT", { cars });
  document.querySelector("#demo-reset")?.removeAttribute("hidden");
}

function demoShowEnded(brand = "") {
  const name = brand ? `«${brand}»` : "";
  document.body.replaceChildren();
  const box = document.createElement("main");
  box.className = "demo-ended";
  const title = document.createElement("h1");
  title.textContent = `Демо ${name} завершено`.replace("  ", " ");
  const text = document.createElement("p");
  text.textContent = "Срок демо-версии закончился. Чтобы запустить свой бот, напишите тому, кто прислал ссылку.";
  box.append(title, text);
  document.body.append(box);
}

// Подписи разделов; демо под перегонщика меняет их на свои («В Кемерово», «Под заказ»).
const LOCATION_NAMES = { city: "В городе", port: "В порту" };
function locationName(location) {
  return location === "port" ? LOCATION_NAMES.port : LOCATION_NAMES.city;
}

// Цвета, подписи и логотип перегонщика — те же поля demo.json, что и у витрины.
function demoApplyLook(demo) {
  for (const [name, value] of Object.entries(demo.vars || {})) {
    if (/^--[a-z0-9-]+$/.test(name) && /^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(String(value))) {
      document.documentElement.style.setProperty(name, value);
    }
  }
  if (/^#[0-9a-f]{6}$/i.test(demo.color || "")) document.documentElement.style.setProperty("--coral", demo.color);
  const texts = demo.texts || {};
  for (const key of ["city", "port"]) {
    if (typeof texts[key] !== "string" || !texts[key].trim()) continue;
    LOCATION_NAMES[key] = texts[key];
    const option = elements.form.elements.location?.querySelector(`option[value="${key}"]`);
    if (option) option.textContent = texts[key];
  }
  if (/^\/demos\/[a-z0-9-]+\/[\w.-]+$/.test(demo.logo || "")) {
    document.querySelectorAll("[data-brand-initials]").forEach((node) => {
      const image = document.createElement("img");
      image.src = demo.logo;
      image.alt = "";
      node.replaceChildren(image);
    });
  }
  try { telegram?.setHeaderColor(getComputedStyle(document.documentElement).getPropertyValue("--dark").trim()); } catch (_error) { /* старые клиенты Telegram */ }
}

function demoApplyBrand(name) {
  const clean = String(name).replace(/[^\p{L}\p{N} .&«»"'-]/gu, "").trim().slice(0, 40);
  if (!clean) return;
  const words = clean.split(/[\s-]+/).filter(Boolean);
  const initials = words.length > 1
    ? (words[0][0] + words[1][0]).toUpperCase()
    : clean.slice(0, 2).toUpperCase();
  document.querySelectorAll("[data-brand-name]").forEach((node) => { node.textContent = clean; });
  document.querySelectorAll("[data-brand-initials]").forEach((node) => { node.textContent = initials; });
  document.title = `Демо-админка — ${clean}`;
}

function demoLeads(cars) {
  const carName = (index) => {
    const car = cars[index % Math.max(cars.length, 1)];
    return car ? `${car.brand} ${car.model} (${car.year})` : "Нужна помощь с выбором";
  };
  const ago = (hours) => new Date(Date.now() - hours * 3_600_000).toISOString();
  return [
    { name: "Алексей", phone: "+7 900 000-00-01", source: "telegram", lead_type: "car", car_interest: carName(0), purchase_method: "Наличные", status: "new", note: "", comment: "Можно посмотреть в субботу?", created_at: ago(2) },
    { name: "Марина", phone: "+7 900 000-00-02", source: "site", lead_type: "manager", car_interest: "Нужна помощь с выбором", purchase_method: "Кредит", status: "new", note: "", comment: "Семейный кроссовер до 4 млн ₽", created_at: ago(9) },
    { name: "Дмитрий", phone: "+7 900 000-00-03", source: "telegram", lead_type: "car", car_interest: carName(1), purchase_method: "Трейд-ин", status: "in_work", note: "Перезвонить в пятницу", handled_by: "manager_anna", comment: "", created_at: ago(30) },
    { name: "Ольга", phone: "+7 900 000-00-04", source: "telegram", lead_type: "car", car_interest: carName(2), purchase_method: "Наличные", status: "won", note: "Купила, выдача в среду", handled_by: "owner", comment: "", created_at: ago(80) },
    { name: "Сергей", phone: "+7 900 000-00-05", source: "site", lead_type: "car", car_interest: carName(3), purchase_method: "Кредит", status: "lost", note: "Взял у дилера", handled_by: "manager_anna", comment: "", created_at: ago(200), is_archived: true },
  ].map((lead, index) => ({
    id: index + 1, username: "", contact_username: "", handled_by: "", is_archived: false, ...lead,
  }));
}

async function demoSeed() {
  const slug = demoSlug();
  let cars = [];
  let slugLoaded = false;
  if (slug) {
    const response = await fetch(`/api/demos/${slug}`, { headers: demoHeaders() }).catch(() => null);
    if (response?.status === 410) {
      demoShowEnded((await response.json().catch(() => ({}))).brand || "");
      return new Promise(() => {});
    }
    const demo = response?.ok ? await response.json().catch(() => null) : null;
    if (demo?.sandbox) document.querySelector("#demo-reset")?.removeAttribute("hidden");
    if (demo?.brand) demoApplyBrand(demo.brand);
    if (demo) demoApplyLook(demo);
    cars = demo?.cars || [];
    const siteLink = document.querySelector("#admin-site-link");
    if (siteLink && demo) siteLink.href = `/?demo=${slug}`;
    // Демо перегонщика не подменяем общим: даже если он удалил все машины.
    if (demo) slugLoaded = true;
  }
  if (!slugLoaded && !cars.length) cars = (await demoFetchJson("/api/cars"))?.cars || [];
  let imageId = 1000;
  cars = cars.map((car, index) => ({
    is_visible: true, is_sold: false, sold_at: null, sort_order: index, description: "",
    ...car,
    images: (car.images || []).map((image) => ({ ...image, id: imageId++ })),
  }));
  return {
    cars,
    leads: demoLeads(cars),
    users: [
      { ...DEMO_OWNER, is_active: true },
      { id: 2, username: "manager_anna", role: "manager", is_active: true },
    ],
    actions: [],
    nextImageId: imageId,
    nextUserId: 3,
  };
}

const demoCopy = (value) => JSON.parse(JSON.stringify(value));

async function demoApi(url, options = {}) {
  const data = await (demoReady ??= demoSeed());
  const method = (options.method || "GET").toUpperCase();
  const body = typeof options.body === "string" ? JSON.parse(options.body) : options.body;
  const [section, rawId, sub] = new URL(url, location.origin).pathname
    .replace(/^\/api\/admin\/?/, "")
    .split("/")
    .map(decodeURIComponent);
  const fail = (message) => { throw new Error(message); };
  const log = (action, target = "") => data.actions.unshift({
    username: DEMO_OWNER.username, action, target, created_at: new Date().toISOString(),
  });
  const findCar = (id) => data.cars.find((car) => car.id === id) || fail("Автомобиль не найден");

  if (section === "cars" && !rawId && method === "GET") {
    return { cars: demoCopy([...data.cars].sort((a, b) => a.sort_order - b.sort_order)) };
  }
  if (section === "cars" && !rawId && method === "POST") {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(body.id || "")) fail("ID — латиница, цифры и дефис");
    if (data.cars.some((car) => car.id === body.id)) fail("Карточка с таким ID уже есть");
    const { original_id: _ignored, ...fields } = body;
    const car = { ...fields, images: [], is_sold: false, sold_at: null, created_at: new Date().toISOString() };
    data.cars.push(car);
    await demoPersist(data);
    log("Добавил автомобиль", `${car.brand} ${car.model}`);
    return { car: demoCopy(car) };
  }
  if (section === "cars" && rawId && !sub && method === "PUT") {
    const car = findCar(rawId);
    const { original_id: _ignored, id: _id, ...fields } = body;
    Object.assign(car, fields);
    await demoPersist(data);
    log("Изменил автомобиль", `${car.brand} ${car.model}`);
    return { car: demoCopy(car) };
  }
  if (section === "cars" && rawId && !sub && method === "DELETE") {
    const car = findCar(rawId);
    data.cars = data.cars.filter((item) => item !== car);
    await demoPersist(data);
    log("Удалил автомобиль", `${car.brand} ${car.model}`);
    return null;
  }
  if (section === "cars" && sub === "images" && method === "POST") {
    const car = findCar(rawId);
    const files = body.getAll("image");
    // В демо перегонщика фото уходят в его песочницу, иначе живут только во вкладке.
    const urls = demoSlug()
      ? (await demoSend(`/api/demos/${demoSlug()}/sandbox/photos`, "POST", body)).urls
      : files.map((file) => URL.createObjectURL(file));
    for (const url of urls) {
      car.images.push({
        id: data.nextImageId++, car_id: car.id, url,
        alt_text: `${car.brand} ${car.model}`, sort_order: car.images.length,
      });
    }
    await demoPersist(data);
    log("Загрузил фото", `${car.brand} ${car.model}`);
    return { ok: true };
  }
  if (section === "cars" && sub === "sold" && method === "POST") {
    const car = findCar(rawId);
    car.is_sold = Boolean(body.sold);
    car.sold_at = car.is_sold ? new Date().toISOString() : null;
    await demoPersist(data);
    log(car.is_sold ? "Отметил проданным" : "Вернул в продажу", `${car.brand} ${car.model}`);
    return { car: demoCopy(car) };
  }
  if (section === "images" && method === "DELETE") {
    data.cars.forEach((car) => { car.images = car.images.filter((image) => String(image.id) !== rawId); });
    await demoPersist(data);
    return null;
  }
  if (section === "summary") {
    const weekAgo = Date.now() - 7 * 86_400_000;
    return {
      cars: data.cars.filter((car) => !car.is_sold).length,
      hidden: data.cars.filter((car) => !car.is_sold && !car.is_visible).length,
      sold: data.cars.filter((car) => car.is_sold).length,
      leads_week: data.leads.filter((lead) => Date.parse(lead.created_at) >= weekAgo).length,
      leads_new: data.leads.filter((lead) => lead.status === "new" && !lead.is_archived).length,
    };
  }
  if (section === "session") return { user: demoCopy(DEMO_OWNER) };
  if (section === "users") {
    const user = rawId ? data.users.find((item) => String(item.id) === rawId) || fail("Пользователь не найден") : null;
    if (method === "GET") {
      return {
        users: demoCopy(data.users.map((item) => ({ ...item, can_manage: item.id !== DEMO_OWNER.id }))),
        assignable_roles: ["manager"],
      };
    }
    if (method === "POST") {
      if ((body.username || "").length < 3) fail("Логин — не короче 3 символов");
      if ((body.password || "").length < 12) fail("Пароль — не короче 12 символов");
      if (data.users.some((item) => item.username === body.username)) fail("Такой логин уже есть");
      data.users.push({ id: data.nextUserId++, username: body.username, role: "manager", is_active: true });
      log("Создал пользователя", body.username);
      return { ok: true };
    }
    if (method === "PUT") {
      if (body.password !== undefined && body.password.length < 12) fail("Пароль — не короче 12 символов");
      user.is_active = Boolean(body.is_active);
      log("Изменил доступ", user.username);
      return { ok: true };
    }
    if (method === "DELETE") {
      data.users = data.users.filter((item) => item !== user);
      log("Удалил пользователя", user.username);
      return null;
    }
  }
  if (section === "leads") {
    if (!rawId && method === "GET") return { leads: demoCopy(data.leads) };
    const lead = data.leads.find((item) => String(item.id) === rawId) || fail("Заявка не найдена");
    if (sub === "archive") {
      lead.is_archived = Boolean(body.archived);
      log(lead.is_archived ? "Убрал заявку в архив" : "Вернул заявку из архива", `№${lead.id}`);
      return { ok: true };
    }
    if (method === "PATCH") {
      lead.status = body.status;
      lead.note = body.note;
      if (lead.status !== "new") lead.handled_by = DEMO_OWNER.username;
      log("Обновил заявку", `№${lead.id}`);
      return { ok: true };
    }
    if (method === "DELETE") {
      data.leads = data.leads.filter((item) => item !== lead);
      log("Удалил заявку", `№${lead.id}`);
      return null;
    }
  }
  if (section === "actions") return { actions: demoCopy(data.actions) };
  return fail("В демо это действие недоступно");
}

document.querySelector("#demo-reset")?.addEventListener("click", async () => {
  if (!window.confirm("Вернуть демо к исходным машинам? Ваши изменения удалятся.")) return;
  try {
    await demoSend(`/api/demos/${demoSlug()}/sandbox`, "DELETE");
    location.reload();
  } catch (error) {
    showToast(error.message);
  }
});

loadCars().catch((error) => showToast(error.message)).finally(() => window.__appStarted?.());
loadSummary();
