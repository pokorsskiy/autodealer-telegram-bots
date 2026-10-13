// Вход в админку из Telegram: подписанные данные Web App меняются на сессию.
const statusText = document.querySelector("#telegram-status");
const passwordLogin = document.querySelector("#password-login");
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const telegram = window.Telegram?.WebApp;

function fail(text) {
  statusText.textContent = text;
  passwordLogin.hidden = false;
}

if (!telegram?.initData) {
  fail("Вход без пароля работает, когда админка открыта кнопкой из бота.");
} else {
  telegram.ready();
  telegram.expand();
  fetch("/admin/tg", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify({ init_data: telegram.initData }),
  })
    .then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (response.ok) location.replace(data.redirect || "/admin");
      else fail(data.error || "Не удалось войти через Telegram.");
    })
    .catch(() => fail("Нет связи с сервером. Попробуйте ещё раз."));
}
