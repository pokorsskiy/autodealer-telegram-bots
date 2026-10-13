const telegram = window.Telegram?.WebApp;

// localStorage переживает закрытие приложения, но в приватном режиме бросает
// исключение, поэтому любое обращение к нему прикрыто try/catch.
function readStore(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch (_error) {
    return fallback;
  }
}

function writeStore(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch (_error) {
    // Витрина работает и без сохранения: это лишь удобство.
  }
}

const state = {
  cars: [],
  search: "",
  location: "",
  brand: "",
  maxPrice: "",
  minYear: "",
  maxYear: "",
  maxMileage: "",
  maxEngine: "",
  body: "",
  drive: "",
  sort: "new",
  view: readStore("dealer-auto-view", "grid"),
  favorites: new Set(readStore("dealer-auto-favorites", [])),
  recent: readStore("dealer-auto-recent", []),
  compare: new Set(),
  // Режим приходит из /api/site. В демо заявка не уходит с телефона:
  // вместо отправки показывается образец.
  demo: false,
};

const elements = {
  list: document.querySelector("#car-list"),
  empty: document.querySelector("#empty-state"),
  resultCount: document.querySelector("#result-count"),
  favoriteHead: document.querySelector("#favorite-head"),
  favoriteHeadCount: document.querySelector("#favorite-head-count"),
  activeFilterCount: document.querySelector("#active-filter-count"),
  filtersButton: document.querySelector("#filters-button"),
  filtersPanel: document.querySelector("#filters-panel"),
  search: document.querySelector("#search"),
  brand: document.querySelector("#brand-filter"),
  price: document.querySelector("#price-filter"),
  year: document.querySelector("#year-filter"),
  yearTo: document.querySelector("#year-to-filter"),
  mileage: document.querySelector("#mileage-filter"),
  engine: document.querySelector("#engine-filter"),
  body: document.querySelector("#body-filter"),
  drive: document.querySelector("#drive-filter"),
  sort: document.querySelector("#sort"),
  favoritesDialog: document.querySelector("#favorites-dialog"),
  favoritesList: document.querySelector("#favorites-list"),
  favoritesEmpty: document.querySelector("#favorites-empty"),
  favoritesSummary: document.querySelector("#favorites-summary"),
  carDialog: document.querySelector("#car-dialog"),
  carDialogContent: document.querySelector("#car-dialog-content"),
  leadDialog: document.querySelector("#lead-dialog"),
  leadForm: document.querySelector("#lead-form"),
  carInterest: document.querySelector("#car-interest"),
  leadKicker: document.querySelector("#lead-kicker"),
  leadTitle: document.querySelector("#lead-dialog-title"),
  leadDescription: document.querySelector("#lead-description"),
  leadSample: document.querySelector("#lead-sample"),
  leadSampleMessage: document.querySelector("#lead-sample-message"),
  calculatorForm: document.querySelector("#calculator-form"),
  calculatorPriceLabel: document.querySelector("#calculator-price-label"),
  calculatorPriceHint: document.querySelector("#calculator-price-hint"),
  calculationResult: document.querySelector("#calculation-result"),
  calculatorOrder: document.querySelector("[data-open-order]"),
  recentStrip: document.querySelector("#recent-strip"),
  recentRow: document.querySelector("#recent-row"),
  compareBar: document.querySelector("#compare-bar"),
  compareCount: document.querySelector("#compare-count"),
  compareDialog: document.querySelector("#compare-dialog"),
  compareTable: document.querySelector("#compare-table"),
  toast: document.querySelector("#toast"),
};

// Цвета берём из переменных style.css, чтобы шапка Telegram и браузера
// перекрашивалась вместе с сайтом.
const cssColor = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Вызывается ещё раз после цветов демо, чтобы шапка совпала с фирменными.
function paintChrome() {
  document.querySelector("meta[name='theme-color']")?.setAttribute("content", cssColor("--graphite"));
  telegram?.setHeaderColor?.(cssColor("--graphite"));
  telegram?.setBackgroundColor?.(cssColor("--paper"));
}

if (telegram) {
  telegram.ready();
  telegram.expand();
}
paintChrome();

// Неразрывный пробел: сумма и знак рубля не переносятся на разные строки.
const formatRub = (value) => `${Math.round(value).toLocaleString("ru-RU")} ₽`;
const escapeHtml = (value) => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");
// Подписи разделов; демо под перегонщика может заменить их своими («В Кемерово», «Под заказ»).
const LOCATION_LABELS = { city: "В городе", port: "В порту" };
const locationLabel = (location) => location === "port" ? LOCATION_LABELS.port : LOCATION_LABELS.city;
const firstImage = (car) => car.images?.[0]?.url || "";

const pluralCars = (count) => {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} автомобиль`;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return `${count} автомобиля`;
  return `${count} автомобилей`;
};

let toastTimer;
function showToast(message) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("is-visible"), 2800);
}

function persistFavorites() {
  writeStore("dealer-auto-favorites", [...state.favorites]);
}

function fillSelect(select, values) {
  [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru")).forEach((value) => {
    select.add(new Option(value, value));
  });
}

// Двигатель в карточке — текст («2.0 л · бензин»), поэтому объём достаём
// из него. Без объёма (электромобиль) машина под фильтр по двигателю не попадает.
function engineLiters(car) {
  const match = /(\d+(?:[.,]\d+)?)\s*л(?!\.с)/i.exec(car.engine || "");
  return match ? Number(match[1].replace(",", ".")) : null;
}

function filteredCars() {
  const query = state.search.trim().toLocaleLowerCase("ru");
  const cars = state.cars.filter((car) => {
    const haystack = [car.brand, car.model, car.body, car.drive, car.engine, car.description]
      .join(" ")
      .toLocaleLowerCase("ru");
    const liters = state.maxEngine ? engineLiters(car) : null;
    return (!query || haystack.includes(query))
      && (!state.location || car.location === state.location)
      && (!state.brand || car.brand === state.brand)
      && (!state.maxPrice || car.price <= Number(state.maxPrice))
      && (!state.minYear || car.year >= Number(state.minYear))
      && (!state.maxYear || car.year <= Number(state.maxYear))
      && (!state.maxMileage || car.mileage <= Number(state.maxMileage))
      && (!state.maxEngine || (liters !== null && liters <= Number(state.maxEngine)))
      && (!state.body || car.body === state.body)
      && (!state.drive || car.drive === state.drive);
  });
  const addedAt = (car) => Date.parse(car.created_at || "") || 0;
  return cars.sort((a, b) => {
    if (state.sort === "price-asc") return a.price - b.price;
    if (state.sort === "price-desc") return b.price - a.price;
    if (state.sort === "mileage-asc") return a.mileage - b.mileage;
    if (state.sort === "year-desc") return b.year - a.year;
    if (state.sort === "year-asc") return a.year - b.year;
    return addedAt(b) - addedAt(a) || a.sort_order - b.sort_order;
  });
}

function toggleFavorite(carId) {
  if (state.favorites.has(carId)) {
    state.favorites.delete(carId);
    showToast("Удалено из избранного");
  } else {
    state.favorites.add(carId);
    showToast("Добавлено в избранное");
  }
  persistFavorites();
  render();
  if (elements.favoritesDialog.open) renderFavorites();
}

// Отмечаем только свежие машины и не больше двух, иначе значок перестаёт
// что-либо значить: в каталоге из шести автомобилей «новыми» будут все.
const NEW_ARRIVAL_DAYS = 30;
const NEW_ARRIVAL_LIMIT = 2;
let newArrivalIds = new Set();

function markNewArrivals(cars) {
  const now = Date.now();
  newArrivalIds = new Set(
    cars
      .map((car) => ({ id: car.id, time: Date.parse(car.created_at || "") }))
      .filter(({ time }) => Number.isFinite(time) && now - time <= NEW_ARRIVAL_DAYS * 86_400_000)
      .sort((first, second) => second.time - first.time)
      .slice(0, NEW_ARRIVAL_LIMIT)
      .map(({ id }) => id),
  );
}

const RECENT_LIMIT = 6;
const COMPARE_LIMIT = 3;

function rememberViewed(carId) {
  state.recent = [carId, ...state.recent.filter((id) => id !== carId)].slice(0, RECENT_LIMIT);
  writeStore("dealer-auto-recent", state.recent);
  renderRecent();
}

function renderRecent() {
  const cars = state.recent
    .map((id) => state.cars.find((car) => car.id === id))
    .filter(Boolean);
  elements.recentStrip.hidden = cars.length === 0;
  elements.recentRow.replaceChildren(...cars.map((car) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-card";
    const image = document.createElement("img");
    image.src = firstImage(car);
    image.alt = "";
    image.loading = "lazy";
    const title = document.createElement("b");
    title.textContent = `${car.brand} ${car.model}`;
    button.append(image, title);
    button.addEventListener("click", () => openCar(car.id));
    return button;
  }));
}

function toggleCompare(carId) {
  if (state.compare.has(carId)) {
    state.compare.delete(carId);
  } else {
    if (state.compare.size >= COMPARE_LIMIT) {
      showToast(`Можно сравнить не больше ${COMPARE_LIMIT} автомобилей`);
      return;
    }
    state.compare.add(carId);
  }
  render();
  renderCompareBar();
  if (elements.compareDialog.open) renderCompare();
}

function renderCompareBar() {
  // Сравнение живёт только в текущем сеансе: набор машин быстро устаревает.
  elements.compareBar.hidden = state.compare.size === 0;
  elements.compareCount.textContent = pluralCars(state.compare.size);
}

const COMPARE_ROWS = [
  ["Цена", (car) => formatRub(car.price)],
  ["Год", (car) => String(car.year)],
  ["Пробег", (car) => `${car.mileage.toLocaleString("ru-RU")} км`],
  ["Двигатель", (car) => car.engine],
  ["Мощность", (car) => car.power],
  ["Привод", (car) => car.drive],
  ["Кузов", (car) => car.body],
  ["Статус", (car) => locationLabel(car.location)],
];

function renderCompare() {
  const cars = state.cars.filter((car) => state.compare.has(car.id));
  if (!cars.length) {
    elements.compareTable.innerHTML = "<p>Добавьте автомобили кнопкой «Сравнить» в карточке.</p>";
    return;
  }
  const head = cars
    .map((car) => `<th><b>${escapeHtml(car.brand)} ${escapeHtml(car.model)}</b></th>`)
    .join("");
  const rows = COMPARE_ROWS.map(([label, value]) => {
    const cells = cars.map((car) => `<td>${escapeHtml(value(car))}</td>`).join("");
    return `<tr><th scope="row">${label}</th>${cells}</tr>`;
  }).join("");
  elements.compareTable.innerHTML = `<table><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table>`;
}

function openCompare() {
  renderCompare();
  elements.compareDialog.showModal();
}

// Лента фотографий: на телефоне листается пальцем (scroll-snap докручивает
// до ближайшего фото), на компьютере — кнопками через go().
function photoStrip(images, altFor, onChange, { lazy = true } = {}) {
  const strip = document.createElement("div");
  strip.className = "photo-strip";
  // Сразу грузится только первое фото, остальные — когда человек начинает листать.
  // Иначе каталог тянет все фото всех машин разом: на медленном мобильном
  // интернете и через VPN это минуты ожидания.
  images.forEach((photo, index) => {
    const image = document.createElement("img");
    if (photo.url && index === 0) image.src = photo.url;
    else if (photo.url) image.dataset.src = photo.url;
    image.alt = altFor(photo, index);
    image.loading = lazy || index ? "lazy" : "eager";
    image.draggable = false;
    image.addEventListener("error", () => image.removeAttribute("src"));
    strip.append(image);
  });
  const reveal = (index) => {
    for (const image of [strip.children[index], strip.children[index + 1]]) {
      if (image?.dataset.src) {
        image.src = image.dataset.src;
        delete image.dataset.src;
      }
    }
  };
  if (!lazy) reveal(0);
  strip.addEventListener("pointerdown", () => reveal(0), { once: true, passive: true });
  let current = 0;
  strip.addEventListener("scroll", () => {
    const index = Math.round(strip.scrollLeft / strip.clientWidth);
    reveal(Math.max(index, 0));
    if (index !== current && index >= 0 && index < images.length) {
      current = index;
      onChange(index);
    }
  }, { passive: true });
  const go = (index) => {
    const target = (index + images.length) % images.length;
    reveal(target);
    strip.scrollTo({ left: target * strip.clientWidth, behavior: "smooth" });
  };
  return { strip, go, current: () => current };
}

function carCard(car) {
  const article = document.createElement("article");
  article.className = "car-card";

  const media = document.createElement("div");
  media.className = "car-card__media";
  const photos = car.images.length ? car.images : [{ url: "" }];
  let dotItems = [];
  const gallery = photoStrip(
    photos,
    (photo, index) => photo.alt_text || `${car.brand} ${car.model}, ${car.year}${index ? `, фото ${index + 1}` : ""}`,
    (index) => dotItems.forEach((dot, dotIndex) => dot.classList.toggle("is-active", dotIndex === Math.min(index, 4))),
  );
  const status = document.createElement("span");
  status.className = `car-card__status ${car.location}`;
  status.textContent = locationLabel(car.location);
  const favorite = document.createElement("button");
  favorite.type = "button";
  favorite.className = `favorite-button ${state.favorites.has(car.id) ? "is-active" : ""}`;
  favorite.textContent = state.favorites.has(car.id) ? "♥︎" : "♡︎";
  favorite.setAttribute("aria-label", `${state.favorites.has(car.id) ? "Удалить" : "Добавить"} ${car.brand} ${car.model} ${state.favorites.has(car.id) ? "из" : "в"} избранное`);
  favorite.addEventListener("click", () => toggleFavorite(car.id));
  media.append(gallery.strip, status, favorite);
  // Фото тоже открывает карточку; сердечко и листание работают сами по себе.
  media.addEventListener("click", (event) => {
    if (!event.target.closest("button")) openCar(car.id);
  });
  if (car.images.length > 1) {
    const dots = document.createElement("span");
    dots.className = "car-card__dots";
    dotItems = car.images.slice(0, 5).map(() => document.createElement("i"));
    dotItems[0].classList.add("is-active");
    dotItems.forEach((dot) => dots.append(dot));
    const next = document.createElement("button");
    next.type = "button";
    next.className = "card-gallery-next";
    next.textContent = "→";
    next.setAttribute("aria-label", "Следующее фото");
    next.addEventListener("click", () => gallery.go(gallery.current() + 1));
    media.append(dots, next);
  }

  const body = document.createElement("button");
  body.type = "button";
  body.className = "car-card__body";
  body.innerHTML = `
    <span class="car-card__brand">${escapeHtml(car.brand)}</span>
    <span class="car-card__title">${escapeHtml(car.model)}</span>
    <span class="car-card__meta">${car.year} · ${car.mileage.toLocaleString("ru-RU")} км · ${escapeHtml(car.drive)}</span>
    <span class="car-card__price">${formatRub(car.price)}${newArrivalIds.has(car.id) ? '<span class="car-card__new">Новое</span>' : ""}</span>
  `;
  body.addEventListener("click", () => openCar(car.id));
  article.append(media, body);
  return article;
}

function render() {
  const visible = filteredCars();
  elements.list.classList.toggle("is-list", state.view === "list");
  elements.list.replaceChildren(...visible.map(carCard));
  elements.empty.hidden = visible.length !== 0;
  elements.resultCount.textContent = pluralCars(visible.length);
  elements.favoriteHeadCount.textContent = state.favorites.size;
  const activeFilters = [
    state.brand, state.maxPrice, state.minYear, state.maxYear, state.maxMileage,
    state.maxEngine, state.body, state.drive,
  ].filter(Boolean).length;
  elements.activeFilterCount.textContent = activeFilters;
  elements.activeFilterCount.hidden = activeFilters === 0;

  document.querySelectorAll("[data-location]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.location === state.location);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === state.view);
  });
}

function favoriteRow(car) {
  const article = document.createElement("article");
  article.className = "favorite-row";
  const image = document.createElement("img");
  image.src = firstImage(car);
  image.alt = `${car.brand} ${car.model}`;
  image.loading = "lazy";

  const content = document.createElement("button");
  content.type = "button";
  content.className = "favorite-row__content";
  const title = document.createElement("b");
  title.textContent = `${car.brand} ${car.model}`;
  const meta = document.createElement("span");
  meta.textContent = `${car.year} · ${locationLabel(car.location)}`;
  const price = document.createElement("strong");
  price.textContent = formatRub(car.price);
  content.append(title, meta, price);
  content.addEventListener("click", () => {
    elements.favoritesDialog.close();
    openCar(car.id);
  });

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "favorite-row__remove";
  remove.textContent = "×";
  remove.setAttribute("aria-label", `Удалить ${car.brand} ${car.model} из избранного`);
  remove.addEventListener("click", () => toggleFavorite(car.id));
  article.append(image, content, remove);
  return article;
}

function renderFavorites() {
  const favorites = state.cars.filter((car) => state.favorites.has(car.id));
  elements.favoritesList.replaceChildren(...favorites.map(favoriteRow));
  elements.favoritesList.hidden = favorites.length === 0;
  elements.favoritesEmpty.hidden = favorites.length !== 0;
  elements.favoritesSummary.textContent = pluralCars(favorites.length);
}

function openFavorites() {
  renderFavorites();
  elements.favoritesDialog.showModal();
}

function openCar(carId) {
  const car = state.cars.find((item) => item.id === carId);
  if (!car) return;
  const images = car.images.length ? car.images : [{ url: "", alt_text: `${car.brand} ${car.model}` }];
  elements.carDialogContent.innerHTML = `
    <div class="car-gallery">
      <span class="gallery-count">1 / ${images.length}</span>
      ${images.length > 1 ? '<div class="gallery-nav"><button type="button" data-prev aria-label="Предыдущее фото">←</button><button type="button" data-next aria-label="Следующее фото">→</button></div>' : ""}
    </div>
    <div class="car-detail">
      <div class="car-detail__top">
        <div><p class="eyebrow">${escapeHtml(locationLabel(car.location))} · ${car.year}</p><h2 id="car-dialog-title">${escapeHtml(car.brand)} ${escapeHtml(car.model)}</h2></div>
        <button class="favorite-button ${state.favorites.has(car.id) ? "is-active" : ""}" type="button" data-detail-favorite>${state.favorites.has(car.id) ? "♥︎" : "♡︎"}</button>
      </div>
      <p class="car-detail__price">${formatRub(car.price)}</p>
      <dl class="detail-specs">
        <div><dt>Пробег</dt><dd>${car.mileage.toLocaleString("ru-RU")} км</dd></div>
        <div><dt>Кузов</dt><dd>${escapeHtml(car.body)}</dd></div>
        <div><dt>Привод</dt><dd>${escapeHtml(car.drive)}</dd></div>
        <div><dt>Двигатель</dt><dd>${escapeHtml(car.engine)}</dd></div>
        <div><dt>Мощность</dt><dd>${escapeHtml(car.power)}</dd></div>
        <div><dt>Статус</dt><dd>${escapeHtml(locationLabel(car.location))}</dd></div>
      </dl>
      <p class="car-detail__description">${escapeHtml(car.description)}</p>
      <div class="car-detail__actions">
        <button class="primary-button" type="button" data-discuss>Обсудить с менеджером <span>→</span></button>
        <button class="ghost-button" type="button" data-compare>${state.compare.has(car.id) ? "Убрать из сравнения" : "Добавить к сравнению"}</button>
        <button class="ghost-button" type="button" data-share>Поделиться</button>
      </div>
    </div>
  `;
  const galleryCount = elements.carDialogContent.querySelector(".gallery-count");
  const gallery = photoStrip(
    images,
    (photo) => photo.alt_text || `${car.brand} ${car.model}`,
    (index) => { galleryCount.textContent = `${index + 1} / ${images.length}`; },
    { lazy: false },
  );
  elements.carDialogContent.querySelector(".car-gallery").prepend(gallery.strip);
  elements.carDialogContent.querySelector("[data-prev]")?.addEventListener("click", () => gallery.go(gallery.current() - 1));
  elements.carDialogContent.querySelector("[data-next]")?.addEventListener("click", () => gallery.go(gallery.current() + 1));
  elements.carDialogContent.querySelector("[data-detail-favorite]").addEventListener("click", () => {
    toggleFavorite(car.id);
    elements.carDialog.close();
    openCar(car.id);
  });
  elements.carDialogContent.querySelector("[data-discuss]").addEventListener("click", () => openLead("car", car));
  elements.carDialogContent.querySelector("[data-share]").addEventListener("click", () => shareCar(car));
  elements.carDialogContent.querySelector("[data-compare]").addEventListener("click", () => {
    toggleCompare(car.id);
    elements.carDialog.close();
  });
  rememberViewed(car.id);
  elements.carDialog.showModal();
}

function fillTelegramUser() {
  const user = telegram?.initDataUnsafe?.user;
  if (!user) return;
  elements.leadForm.elements.name.value = [user.first_name, user.last_name].filter(Boolean).join(" ");
  elements.leadForm.elements.username.value = user.username ? `@${user.username}` : "";
}

function openLead(type, car = null, context = "") {
  const isOrder = context === "order";
  if (elements.carDialog.open) elements.carDialog.close();
  elements.leadForm.reset();
  elements.leadForm.hidden = false;
  elements.leadSample.hidden = true;
  fillTelegramUser();
  elements.leadForm.elements.lead_type.value = type;
  elements.leadForm.elements.car_id.value = car?.id || "";
  const comment = elements.leadForm.elements.comment;
  comment.required = type === "manager";
  comment.placeholder = type === "manager"
    ? "Например: семейный кроссовер до 5 млн ₽"
    : "Комплектация, цвет и другие пожелания";
  comment.closest("label").querySelector("small").textContent = type === "manager" ? "обязательно" : "необязательно";
  elements.carInterest.value = car
    ? `${car.brand} ${car.model} (${car.year})`
    : isOrder ? "Автомобиль под заказ" : "Нужна помощь с выбором";
  elements.leadKicker.textContent = type === "car"
    ? locationLabel(car.location)
    : isOrder ? "Автомобиль под заказ" : "Персональный подбор";
  elements.leadTitle.textContent = type === "car"
    ? "Обсудить автомобиль"
    : isOrder ? "Сделать заказ" : "Подобрать автомобиль";
  elements.leadDescription.textContent = type === "car"
    ? `${car.brand} ${car.model} уже добавлен в заявку. Оставьте контакты.`
    : isOrder
      ? "Оставьте контакты и опишите, какой автомобиль вам нужен."
      : "Опишите задачу — менеджер предложит подходящие варианты.";
  elements.leadDialog.showModal();
}

function resetFilters() {
  Object.assign(state, {
    search: "", brand: "", maxPrice: "", minYear: "", maxYear: "", maxMileage: "",
    maxEngine: "", body: "", drive: "",
  });
  [
    elements.search, elements.brand, elements.price, elements.year, elements.yearTo,
    elements.mileage, elements.engine, elements.body, elements.drive,
  ].forEach((field) => { field.value = ""; });
  render();
}

const engineRate = (engineCc, brackets) => brackets.find(([limit]) => engineCc <= limit)?.[1] ?? brackets.at(-1)[1];
function calculateDutyEur(priceEur, age, engineCc) {
  if (age === "under_3") {
    const brackets = [
      [8_500, .54, 2.5], [16_700, .48, 3.5], [42_300, .48, 5.5],
      [84_500, .48, 7.5], [169_000, .48, 15], [Infinity, .48, 20],
    ];
    const [, percent, minPerCc] = brackets.find(([limit]) => priceEur <= limit);
    return Math.max(priceEur * percent, engineCc * minPerCc);
  }
  if (age === "3_to_5") {
    return engineCc * engineRate(engineCc, [[1000, 1.5], [1500, 1.7], [1800, 2.5], [2300, 2.7], [3000, 3], [10000, 3.6]]);
  }
  return engineCc * engineRate(engineCc, [[1000, 3], [1500, 3.2], [1800, 3.5], [2300, 4.8], [3000, 5], [10000, 5.7]]);
}

function updateCalculatorMode() {
  const mode = elements.calculatorForm.elements.price_mode.value;
  const isBudget = mode === "budget";
  elements.calculatorPriceLabel.textContent = isBudget
    ? "Сколько готовы потратить под ключ, ₽"
    : "Стоимость автомобиля за границей, ₽";
  elements.calculatorPriceHint.textContent = isBudget
    ? "Укажите сумму целиком: автомобиль, пошлина, сборы и доставка. Посчитаем, на какую машину её хватит."
    : "Введите известную стоимость автомобиля без доставки и оформления.";
  elements.calculationResult.hidden = true;
  elements.calculatorOrder.hidden = true;
}

// Курс, доставка и ставки утильсбора совпадают с калькулятором в ботах.
const EUR_RATE = 100;
const DELIVERY_RUB = 450_000;
const PRICE_STEP_RUB = 10_000;

function calculateImport(priceRub, age, engineCc) {
  const duty = calculateDutyEur(priceRub / EUR_RATE, age, engineCc) * EUR_RATE;
  const recycling = age === "under_3" ? 3_400 : 5_200;
  return {
    price: priceRub,
    duty,
    recycling,
    total: priceRub + duty + recycling + DELIVERY_RUB,
  };
}

// Пошлина зависит от цены автомобиля, поэтому вычесть расходы из бюджета
// напрямую нельзя: подбираем наибольшую цену, которая в него укладывается.
function calculateFromBudget(budgetRub, age, engineCc) {
  let low = 0;
  let high = budgetRub;
  let best = null;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const attempt = calculateImport(middle, age, engineCc);
    if (attempt.total <= budgetRub) {
      best = attempt;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  if (!best || best.price < PRICE_STEP_RUB) return null;
  // Округляем вниз: вверх — вышли бы за бюджет.
  return calculateImport(Math.floor(best.price / PRICE_STEP_RUB) * PRICE_STEP_RUB, age, engineCc);
}

elements.calculatorForm.querySelectorAll("[name='price_mode']")
  .forEach((field) => field.addEventListener("change", updateCalculatorMode));

elements.calculatorForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!elements.calculatorForm.reportValidity()) return;
  const values = Object.fromEntries(new FormData(elements.calculatorForm));
  const amountRub = Number(values.price);
  const isBudget = values.price_mode === "budget";
  const engineCc = Math.round(Number(values.engine) * 1000);
  const result = isBudget
    ? calculateFromBudget(amountRub, values.age, engineCc)
    : calculateImport(amountRub, values.age, engineCc);

  if (!result) {
    elements.calculationResult.innerHTML = `
      <h3>Бюджета не хватает</h3>
      <p>Пошлина, сборы и доставка съедают сумму целиком. Попробуйте бюджет побольше
      или автомобиль постарше и с двигателем поменьше.</p>
    `;
    elements.calculationResult.hidden = false;
    elements.calculatorOrder.hidden = false;
    return;
  }

  const priceRow = isBudget
    ? `<dt>Автомобиль за границей</dt><dd>до ${formatRub(result.price)}</dd>`
    : `<dt>Автомобиль</dt><dd>${formatRub(result.price)}</dd>`;
  const summary = isBudget
    ? `<h3>до ${formatRub(result.price)}</h3><p class="calculation-total">Итого ${formatRub(result.total)} из ${formatRub(amountRub)}, остаётся ${formatRub(amountRub - result.total)}</p>`
    : `<h3>${formatRub(result.total)}</h3>`;
  elements.calculationResult.innerHTML = `
    ${summary}
    <dl>${priceRow}<dt>Таможенная пошлина</dt><dd>${formatRub(result.duty)}</dd><dt>Утилизационный сбор</dt><dd>${formatRub(result.recycling)}</dd><dt>Доставка и расходы</dt><dd>${formatRub(DELIVERY_RUB)}</dd></dl>
    <p>${isBudget ? "Цена автомобиля подобрана под ваш бюджет. " : ""}Предварительный расчёт по условному курсу 1 € = ${EUR_RATE} ₽. Точную стоимость уточнит менеджер.</p>
  `;
  elements.calculationResult.hidden = false;
  elements.calculatorOrder.hidden = false;
});

elements.leadForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!elements.leadForm.reportValidity()) return;
  const lead = Object.fromEntries(new FormData(elements.leadForm));
  Object.keys(lead).forEach((key) => { lead[key] = lead[key].trim(); });
  if (lead.name.length < 2 || lead.phone.replace(/\D/g, "").length < 10) {
    showToast("Проверьте имя и номер телефона");
    return;
  }
  const submit = elements.leadForm.querySelector("[type='submit']");
  if (state.demo) {
    showLeadSample(lead);
    return;
  }
  submit.disabled = true;
  submit.firstChild.textContent = "Отправляем ";
  sendLead(lead, submit);
});

// Образец повторяет уведомление менеджеру. Из формы берём только автомобиль
// и способ покупки: контакты в нём вымышленные, введённое никуда не уходит.
function showLeadSample(lead) {
  const isCar = lead.lead_type === "car";
  const lines = [
    `🔥 <b>${isCar ? "Заявка на автомобиль" : "Помощь с выбором"} №128</b>`,
    "",
    "📍 <b>Источник:</b> Иван Петров (@ivan_petrov)",
    "✍️ <b>Имя:</b> Иван Петров",
    "📞 <b>Телефон:</b> +7 900 000-00-00",
    "💬 <b>Username:</b> @ivan_petrov",
    `🚗 <b>Автомобиль:</b> ${escapeHtml(lead.car_interest)}`,
    `💳 <b>Покупка:</b> ${escapeHtml(lead.purchase_method)}`,
    `📝 <b>Комментарий:</b> ${isCar ? "Хочу посмотреть машину на этой неделе" : "Семейный кроссовер до 5 млн ₽"}`,
  ];
  elements.leadSampleMessage.innerHTML = `${lines.join("<br>")}<span class="lead-sample__button">Взял в работу</span>`;
  elements.leadForm.hidden = true;
  elements.leadSample.hidden = false;
  elements.leadDialog.scrollTop = 0;
}

async function sendLead(lead, submit) {
  // Заявку всегда принимает сервер витрины. Внутри Telegram прикладываем
  // подписанные данные запуска — по ним сервер узнаёт профиль клиента.
  // telegram.sendData не годится: Telegram принимает его только от Web App,
  // открытых кнопкой клавиатуры, а у ботов кнопки inline.
  if (isInsideTelegram()) lead.init_data = telegram.initData;
  try {
    const response = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(lead),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || "Не удалось отправить заявку");
    elements.leadDialog.close();
    showToast(
      result.delivered
        ? "Заявка отправлена, менеджер свяжется с вами"
        : "Заявка принята, менеджер свяжется с вами",
    );
  } catch (error) {
    showToast(error.message || "Не удалось отправить заявку");
  } finally {
    submit.disabled = false;
    submit.firstChild.textContent = "Отправить заявку ";
  }
}

elements.search.addEventListener("input", (event) => { state.search = event.target.value; render(); });
elements.search.addEventListener("keydown", (event) => {
  if (event.key === "Enter") elements.search.blur();
});
elements.brand.addEventListener("change", (event) => { state.brand = event.target.value; render(); });
elements.price.addEventListener("input", (event) => { state.maxPrice = event.target.value; render(); });
elements.year.addEventListener("input", (event) => { state.minYear = event.target.value; render(); });
elements.yearTo.addEventListener("input", (event) => { state.maxYear = event.target.value; render(); });
elements.mileage.addEventListener("input", (event) => { state.maxMileage = event.target.value; render(); });
elements.engine.addEventListener("input", (event) => { state.maxEngine = event.target.value; render(); });
elements.body.addEventListener("change", (event) => { state.body = event.target.value; render(); });
elements.drive.addEventListener("change", (event) => { state.drive = event.target.value; render(); });
elements.sort.addEventListener("change", (event) => { state.sort = event.target.value; render(); });
elements.filtersButton.addEventListener("click", () => {
  elements.filtersPanel.hidden = !elements.filtersPanel.hidden;
  elements.filtersButton.setAttribute("aria-expanded", String(!elements.filtersPanel.hidden));
});
elements.favoriteHead.addEventListener("click", openFavorites);
document.querySelectorAll("[data-location]").forEach((button) => button.addEventListener("click", () => {
  state.location = button.dataset.location;
  render();
}));
document.querySelectorAll("[data-location-jump]").forEach((button) => button.addEventListener("click", () => {
  state.location = button.dataset.locationJump;
  document.querySelector("#catalog").scrollIntoView({ behavior: "smooth" });
  render();
}));
document.querySelector("[data-calculator-jump]").addEventListener("click", () => {
  document.querySelector("#calculator").scrollIntoView({ behavior: "smooth" });
});
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => {
  state.view = button.dataset.view;
  writeStore("dealer-auto-view", state.view);
  render();
}));
document.querySelector("#reset-filters").addEventListener("click", resetFilters);
document.querySelector("[data-reset]").addEventListener("click", resetFilters);
document.querySelector("[data-close-car]").addEventListener("click", () => elements.carDialog.close());
document.querySelector("[data-close-compare]").addEventListener("click", () => elements.compareDialog.close());
document.querySelector("#compare-open").addEventListener("click", openCompare);
document.querySelector("#compare-clear").addEventListener("click", () => {
  state.compare.clear();
  renderCompareBar();
  render();
});
document.querySelector("#clear-recent").addEventListener("click", () => {
  state.recent = [];
  writeStore("dealer-auto-recent", state.recent);
  renderRecent();
});
document.querySelectorAll("[data-close-lead]").forEach((button) => {
  button.addEventListener("click", () => elements.leadDialog.close());
});
document.querySelectorAll("[data-close-favorites]").forEach((button) => {
  button.addEventListener("click", () => elements.favoritesDialog.close());
});
document.querySelector("[data-open-manager]").addEventListener("click", () => openLead("manager"));
document.querySelector("[data-open-order]").addEventListener("click", () => openLead("manager", null, "order"));
[elements.favoritesDialog, elements.carDialog, elements.leadDialog, elements.compareDialog].forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
});

function applyStartParams() {
  // Ссылка из бота может нести бюджет и годы выпуска из расчёта
  // или конкретный автомобиль.
  const params = new URLSearchParams(location.search);
  let filtered = false;
  [
    ["max_price", "maxPrice", elements.price],
    ["min_year", "minYear", elements.year],
    ["max_year", "maxYear", elements.yearTo],
  ].forEach(([param, key, field]) => {
    const value = Number(params.get(param));
    if (!Number.isFinite(value) || value <= 0) return;
    state[key] = String(Math.round(value));
    field.value = state[key];
    filtered = true;
  });
  if (filtered) document.querySelector("#catalog")?.scrollIntoView({ behavior: "smooth" });
  const carId = params.get("car");
  if (carId && state.cars.some((car) => car.id === carId)) openCar(carId);
}

function carShareUrl(car) {
  const url = new URL(location.href);
  url.search = "";
  url.hash = "";
  // Машина из демо перегонщика есть только в его каталоге.
  if (demoSlug) url.searchParams.set("demo", demoSlug);
  url.searchParams.set("car", car.id);
  return url.toString();
}

function shareCar(car) {
  const text = `${car.brand} ${car.model}, ${car.year} — ${formatRub(car.price)}`;
  const shareLink = `https://t.me/share/url?url=${encodeURIComponent(carShareUrl(car))}`
    + `&text=${encodeURIComponent(text)}`;
  if (telegram?.openTelegramLink) {
    telegram.openTelegramLink(shareLink);
    return;
  }
  window.open(shareLink, "_blank", "noopener");
}

// Демо под конкретного перегонщика: ?demo=<имя> — его название, цвет и машины
// из канала. Сервер отдаёт такое демо только в демо-режиме.
const demoSlug = /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(new URLSearchParams(location.search).get("demo") || "")
  ? new URLSearchParams(location.search).get("demo")
  : "";

async function fetchDemo() {
  if (!demoSlug) return null;
  try {
    // Подписанные данные Telegram — чтобы показать машины из демо-админки этого человека.
    const headers = { Accept: "application/json" };
    if (telegram?.initData) headers["X-Telegram-Init-Data"] = telegram.initData;
    const response = await fetch(`/api/demos/${demoSlug}`, { headers });
    if (response.status === 410) {
      showDemoEnded((await response.json().catch(() => ({}))).brand || "");
      return { cars: [] };
    }
    if (!response.ok) return null;
    const demo = await response.json();
    if (demo.brand) applyBrand(cleanBrand(demo.brand), true);
    if (demo.color) applyAccent(demo.color);
    applyDemoLook(demo);
    return Array.isArray(demo.cars) && demo.cars.length ? { cars: demo.cars } : null;
  } catch (_error) {
    return null;
  }
}

// Срок демо закончился: вместо каталога — короткое объяснение.
function showDemoEnded(brand) {
  const box = document.createElement("main");
  box.className = "demo-ended";
  const title = document.createElement("h1");
  title.textContent = brand ? `Демо «${brand}» завершено` : "Демо завершено";
  const text = document.createElement("p");
  text.textContent = "Срок демо-версии закончился. Чтобы запустить свой бот, напишите тому, кто прислал ссылку.";
  box.append(title, text);
  document.body.replaceChildren(box);
}

// Свои цвета, подписи и логотип перегонщика из demo.json.
// vars — CSS-переменные (только имена вида --name и цвета #rrggbb);
// texts — подписи элементов с data-text; logo — картинка вместо букв в шапке.
function applyDemoLook(demo) {
  for (const [name, value] of Object.entries(demo.vars || {})) {
    if (/^--[a-z0-9-]+$/.test(name) && /^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(String(value))) {
      document.documentElement.style.setProperty(name, value);
    }
  }
  const texts = demo.texts || {};
  if (texts.city) LOCATION_LABELS.city = String(texts.city);
  if (texts.port) LOCATION_LABELS.port = String(texts.port);
  document.querySelectorAll("[data-text]").forEach((element) => {
    const value = texts[element.dataset.text];
    if (typeof value === "string" && value.trim()) element.textContent = value;
  });
  if (/^\/demos\/[a-z0-9-]+\/[\w.-]+$/.test(demo.logo || "")) {
    document.querySelectorAll("[data-brand-initials]").forEach((element) => {
      const image = document.createElement("img");
      image.src = demo.logo;
      image.alt = "";
      element.replaceChildren(image);
    });
  }
  paintChrome();
}

async function fetchCars() {
  const demo = await fetchDemo();
  if (demo) return demo;
  // На статическом хостинге сервера с /api/cars нет, поэтому витрина
  // показывает демонстрационный каталог вместо пустого экрана.
  try {
    const response = await fetch("/api/cars", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("catalog unavailable");
    return await response.json();
  } catch (_error) {
    const fallback = await fetch("demo-cars.json", { headers: { Accept: "application/json" } });
    if (!fallback.ok) throw new Error("demo catalog unavailable");
    return await fallback.json();
  }
}

async function loadCatalog() {
  try {
    const data = await fetchCars();
    state.cars = Array.isArray(data.cars) ? data.cars : [];
    markNewArrivals(state.cars);
    const validIds = new Set(state.cars.map((car) => car.id));
    state.favorites = new Set([...state.favorites].filter((id) => validIds.has(id)));
    persistFavorites();
    fillSelect(elements.brand, state.cars.map((car) => car.brand));
    fillSelect(elements.body, state.cars.map((car) => car.body));
    fillSelect(elements.drive, state.cars.map((car) => car.drive));
    applyStartParams();
    render();
    renderRecent();
    renderCompareBar();
    if (elements.favoritesDialog.open) renderFavorites();
  } catch (_error) {
    elements.resultCount.textContent = "Каталог недоступен";
    elements.empty.hidden = false;
    elements.empty.querySelector("h3").textContent = "Не удалось загрузить каталог";
    elements.empty.querySelector("p").textContent = "Попробуйте открыть приложение ещё раз.";
  } finally {
    window.__appStarted?.();
  }
}

// SDK подключается и в браузере, поэтому проверяем именно запуск из Telegram:
// вне его sendData молча ничего не делает.
function isInsideTelegram() {
  return Boolean(telegram?.initData)
    && Boolean(telegram.platform)
    && telegram.platform !== "unknown";
}

function openExternal(url) {
  // Ссылки Telegram внутри приложения открываются в самом Telegram, остальные — в браузере.
  if (/^https:\/\/t\.me\//.test(url) && telegram?.openTelegramLink) {
    telegram.openTelegramLink(url);
  } else if (telegram?.openLink) {
    telegram.openLink(url);
  } else {
    window.open(url, "_blank", "noopener");
  }
}

// Политика и согласие открываются отдельной страницей: обычный переход по ссылке
// внутри Telegram увёл бы клиента из витрины вместе с заполненной формой.
document.addEventListener("click", (event) => {
  const link = event.target.closest?.("[data-legal-link]");
  if (!link) return;
  event.preventDefault();
  openExternal(new URL(link.getAttribute("href"), location.origin).href);
});

// Кнопка без адреса не показывается: заглушек «будет позже» в витрине нет.
function wireLink(element) {
  const url = (element?.dataset.url || "").trim();
  if (!url) return false;
  element.hidden = false;
  element.addEventListener("click", () => openExternal(url));
  return true;
}

async function loadLinks() {
  // На своём сервере адреса приходят из .env, на статическом хостинге
  // остаются те, что вписаны в data-url прямо в index.html.
  try {
    const response = await fetch("/api/links", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("links unavailable");
    const links = await response.json();
    document.querySelectorAll("[data-link-name]").forEach((element) => {
      const url = links[element.dataset.linkName];
      if (url) element.dataset.url = url;
    });
  } catch (_error) {
    // Молча: запасной вариант уже лежит в разметке.
  }

  const linkGrid = document.querySelector("#link-grid");
  const configured = [...document.querySelectorAll("[data-link]")].filter(wireLink);
  if (linkGrid && configured.length) linkGrid.hidden = false;
}

// Демо-ссылка для конкретного перегонщика: ?brand=Название подставляет его
// название вместо «АвтоПривоз». Работает только в демо: у заказчика своё
// название, и чужая ссылка не должна его подменять.
const BRAND_MAX_LENGTH = 40;

function brandInitials(name) {
  const words = name.split(/[\s-]+/).filter(Boolean);
  if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase();
  const inner = name.slice(1).match(/\p{Lu}/u);
  return inner ? name[0].toUpperCase() + inner[0] : name.slice(0, 2).toUpperCase();
}

function cleanBrand(raw) {
  return String(raw).replace(/[^\p{L}\p{N} .&«»"'-]/gu, "").replace(/\s+/g, " ").trim()
    .slice(0, BRAND_MAX_LENGTH);
}

// ownCars — в демо машины самого перегонщика, тогда «вымышленные» не пишем.
function applyBrand(name, ownCars = false) {
  if (!name) return;
  document.title = document.title.replace("АвтоПривоз", name);
  document.querySelectorAll("[data-brand-name]").forEach((element) => { element.textContent = name; });
  document.querySelectorAll("[data-brand-initials]").forEach((element) => {
    element.textContent = brandInitials(name);
  });
  document.querySelector("#demo-banner").textContent = `Демо-версия для «${name}»: `
    + (ownCars ? "" : "автомобили вымышленные, ")
    + "заявки никуда не отправляются. Не является публичной офертой.";
}

// Фирменный цвет перегонщика вместо кораллового: кнопки, плашка, акценты.
function applyAccent(color) {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return;
  const darker = "#" + [1, 3, 5]
    .map((start) => Math.round(parseInt(color.slice(start, start + 2), 16) * 0.86)
      .toString(16).padStart(2, "0"))
    .join("");
  document.documentElement.style.setProperty("--coral", color);
  document.documentElement.style.setProperty("--coral-dark", darker);
}

async function loadSite() {
  // Без сервера (статический хостинг) сведений нет: плашка и подвал не меняются.
  try {
    const response = await fetch("/api/site", { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const site = await response.json();
    state.demo = site.demo === true;
    // Название из ?brand — только когда нет полного демо со своим названием.
    if (state.demo && !demoSlug) applyBrand(cleanBrand(new URLSearchParams(location.search).get("brand") || ""));
    document.querySelector("#demo-banner").hidden = !state.demo;
    document.querySelector("#lead-demo-note").hidden = !state.demo;
    const contacts = [site.owner, site.email].filter(Boolean).map(escapeHtml);
    if (site.email) {
      contacts[contacts.length - 1] = `<a href="mailto:${escapeHtml(site.email)}">${escapeHtml(site.email)}</a>`;
    }
    const parts = [];
    parts.push(state.demo
      ? "Демо-витрина, не является публичной офертой."
      : "Цены носят информационный характер и не являются публичной офертой.");
    if (contacts.length) parts.push(`Владелец сайта: ${contacts.join(", ")}.`);
    parts.push('<a href="/privacy" data-legal-link>Политика обработки персональных данных</a>');
    const owner = document.querySelector("#site-owner");
    owner.innerHTML = parts.join(" ");
    owner.hidden = !parts.length;
  } catch (_error) {
    // Молча: витрина работает и без этих сведений.
  }
}

// Телефон: «+7» подставляется сам, цифры раскладываются как +7 999 123-45-67.
function formatPhone(value) {
  let digits = value.replace(/\D/g, "");
  if (value.trim().startsWith("+7")) digits = digits.slice(1);
  // 11 цифр с 8 или 7 впереди — номер набран с кодом страны по привычке
  // (8 999… или +7 8 999…). Городской 812… из 10 цифр остаётся как есть.
  if (digits.length === 11 && /^[78]/.test(digits)) digits = digits.slice(1);
  digits = digits.slice(0, /^[78]/.test(digits) ? 11 : 10);
  if (digits.length === 11) digits = digits.slice(1);
  let result = "+7";
  if (digits.length) result += ` ${digits.slice(0, 3)}`;
  if (digits.length > 3) result += ` ${digits.slice(3, 6)}`;
  if (digits.length > 6) result += `-${digits.slice(6, 8)}`;
  if (digits.length > 8) result += `-${digits.slice(8, 10)}`;
  return result;
}

const phoneInput = elements.leadForm.elements.phone;
phoneInput.addEventListener("focus", () => {
  if (!phoneInput.value) phoneInput.value = "+7 ";
  requestAnimationFrame(() => phoneInput.setSelectionRange(phoneInput.value.length, phoneInput.value.length));
});
phoneInput.addEventListener("input", (event) => {
  // При стирании не переформатируем: иначе пробел и дефис возвращались бы
  // сразу и мешали удалять цифры подряд.
  if (event.inputType?.startsWith("delete")) return;
  phoneInput.value = formatPhone(phoneInput.value);
});
phoneInput.addEventListener("blur", () => {
  phoneInput.value = phoneInput.value.replace(/\D/g, "").length > 1 ? formatPhone(phoneInput.value) : "";
});

// На телефоне клавиатура закрывает нижние поля формы: когда она появилась,
// прокручиваем поле, в котором пишут, в середину экрана.
document.addEventListener("focusin", (event) => {
  const field = event.target;
  if (!field.matches?.("input:not([type=radio]):not([type=checkbox]), textarea, select")) return;
  if (!matchMedia("(pointer: coarse)").matches) return;
  setTimeout(() => field.scrollIntoView({ block: "center", behavior: "smooth" }), 350);
});

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

fillTelegramUser();
loadSite();
loadLinks();
loadCatalog();
