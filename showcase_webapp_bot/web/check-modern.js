// Тот же современный JavaScript, что в каталоге: старый браузер не разберёт файл,
// и флаг не появится. Отдельным файлом — политика безопасности запрещает new Function.
window.__modernOk = (() => {
  let value = null;
  value ??= { ok: 1 };
  return value?.ok === 1 && "ab".replaceAll("b", "c") === "ac";
})();
