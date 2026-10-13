// Проверка телефона для тех, у кого не открывается каталог. Человек присылает
// скриншот, по нему видно: браузер, скорость, что именно не грузится.
// Старый JavaScript без новых возможностей — чтобы страница открылась на любом телефоне.
(function () {
  var list = document.getElementById("list");

  function row(text, state, note) {
    var item = document.createElement("li");
    item.className = state === "bad" ? "is-bad" : state === "wait" ? "is-wait" : "";
    item.appendChild(document.createTextNode(text));
    if (note) {
      var small = document.createElement("small");
      small.appendChild(document.createTextNode(note));
      item.appendChild(small);
    }
    list.appendChild(item);
    return item;
  }

  function update(item, text, ok, note) {
    item.className = ok ? "" : "is-bad";
    item.firstChild.nodeValue = text;
    if (note) {
      var small = document.createElement("small");
      small.appendChild(document.createTextNode(note));
      item.appendChild(small);
    }
  }

  // Понимает ли браузер современный код каталога.
  var modern = window.__modernOk === true;  // ставит check-modern.js
  row(modern ? "Браузер телефона поддерживает каталог" : "Браузер телефона устарел",
    modern ? "" : "bad",
    modern ? "" : "Обновите Telegram, а на Android — «Android System WebView» и Chrome в Google Play.");

  var inTelegram = !!(window.Telegram && window.Telegram.WebApp) || /Telegram/i.test(navigator.userAgent);
  row(inTelegram ? "Открыто в Telegram" : "Открыто в обычном браузере");

  function timed(url, label, done) {
    var item = row(label + " — проверяю…", "wait");
    var started = Date.now();
    var request = new XMLHttpRequest();
    request.open("GET", url + (url.indexOf("?") < 0 ? "?" : "&") + "t=" + started, true);
    request.timeout = 20000;
    request.onload = function () {
      var seconds = ((Date.now() - started) / 1000).toFixed(1);
      var ok = request.status >= 200 && request.status < 400;
      update(item, label + (ok ? " — " + seconds + " с" : " — ошибка " + request.status), ok && seconds < 8,
        ok && seconds >= 8 ? "Очень медленно. Если включён VPN — выключите его." : "");
      if (done) done();
    };
    request.onerror = request.ontimeout = function () {
      update(item, label + " — не загрузилось", false, "Интернет не дотягивается до сервера. Попробуйте без VPN или через Wi-Fi.");
      if (done) done();
    };
    request.send();
  }

  timed("/api/site", "Связь с сервером", function () {
    timed("/app.js", "Загрузка каталога", function () {
      timed("/demo/toyota-camry.png", "Загрузка фото");
    });
  });

  var connection = navigator.connection || {};
  document.getElementById("meta").appendChild(document.createTextNode(
    "Устройство: " + navigator.userAgent +
    (connection.effectiveType ? " · сеть: " + connection.effectiveType : "") +
    " · " + new Date().toLocaleString("ru-RU")
  ));
})();
