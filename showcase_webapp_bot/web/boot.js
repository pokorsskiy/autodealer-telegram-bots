// Страховка запуска: если каталог или админка не запустились (старый браузер
// телефона не понял код, интернет не дотянул данные), человек видит объяснение
// и ссылку на проверку телефона, а не пустой экран.
// Написано на старом JavaScript без новых возможностей, чтобы работать везде.
(function () {
  var started = false;
  var TIMEOUT_MS = 15000;

  window.__appStarted = function () {
    started = true;
    var box = document.getElementById("boot-fail");
    if (box) box.parentNode.removeChild(box);
  };

  function show() {
    if (started || document.getElementById("boot-fail") || !document.body) return;
    var box = document.createElement("div");
    box.id = "boot-fail";
    box.className = "boot-fail";
    box.innerHTML =
      "<div class=\"boot-fail__card\">" +
      "<h2>Не получилось загрузить</h2>" +
      "<p>Чаще всего помогает: <b>выключите VPN</b> и откройте ещё раз — сайт работает без него.</p>" +
      "<button type=\"button\">Попробовать ещё раз</button>" +
      "</div>";
    box.getElementsByTagName("button")[0].onclick = function () { window.location.reload(); };
    document.body.appendChild(box);
  }

  // Ошибка разбора основного скрипта — старый браузер: он уже не запустится.
  window.addEventListener("error", function (event) {
    if (event && event.filename && /\/(app|admin)\.js/.test(event.filename)) show();
  }, true);
  setTimeout(show, TIMEOUT_MS);
})();
