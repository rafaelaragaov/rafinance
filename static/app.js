// RaFinance: comportamento do checkbox "Recorrência" e da seleção de meses.
document.querySelectorAll("[data-recorrencia]").forEach((bloco) => {
  const form = bloco.closest("form");
  const toggle = bloco.querySelector("[data-rec-toggle]");
  const painel = bloco.querySelector("[data-rec-meses]");
  const chips = bloco.querySelector("[data-rec-chips]");
  const campoData = form.querySelector('input[name="data"]');
  const ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

  function marcarTodos(marcado) {
    chips.querySelectorAll("input").forEach((i) => { i.checked = marcado; });
  }

  // 12 meses a partir do mês da data escolhida, todos marcados.
  function montarChips() {
    const [ano, mes] = campoData.value.split("-").map(Number);
    if (!ano || !mes) return;
    chips.replaceChildren();
    for (let i = 0; i < 12; i++) {
      const d = new Date(ano, mes - 1 + i, 1);
      const valor = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      const rotulo = `${ABREV[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`;

      const label = document.createElement("label");
      label.className = "chip";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "meses";
      input.value = valor;
      input.checked = true;
      const texto = document.createElement("span");
      texto.textContent = rotulo;
      label.append(input, texto);
      chips.append(label);
    }
  }

  toggle.addEventListener("change", () => { painel.hidden = !toggle.checked; });
  campoData.addEventListener("change", montarChips);
  bloco.querySelector("[data-rec-todos]").addEventListener("click", () => marcarTodos(true));
  bloco.querySelector("[data-rec-limpar]").addEventListener("click", () => marcarTodos(false));
});
