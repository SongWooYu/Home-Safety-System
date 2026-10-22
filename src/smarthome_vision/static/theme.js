/* Load before styles to avoid a bright flash on a dark desktop. */
(() => {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let choice = "system";
  try { choice = localStorage.getItem("vision-theme") || "system"; } catch (_) {}
  if (!["system", "light", "dark"].includes(choice)) choice = "system";
  function apply() {
    document.documentElement.dataset.theme = choice === "system" ? (media.matches ? "dark" : "light") : choice;
  }
  window.visionTheme = {
    get: () => choice,
    set: value => {
      choice = ["system", "light", "dark"].includes(value) ? value : "system";
      try { localStorage.setItem("vision-theme", choice); } catch (_) {}
      apply();
    }
  };
  media.addEventListener("change", apply);
  apply();
})();
