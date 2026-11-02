// RaFinance: tema (modo + cor), diálogo do "+", quinzena e recorrência.
const ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

/* ---------------------------------------------------------------- tema */
const CHAVE_TEMA = "rafinance-tema";
const raiz = document.documentElement;

function lerTema() {
  try { return JSON.parse(localStorage.getItem(CHAVE_TEMA)) || {}; } catch { return {}; }
}
function salvarTema(tema) {
  try { localStorage.setItem(CHAVE_TEMA, JSON.stringify(tema)); } catch { /* vale só nesta visita */ }
}
function aplicarTema(tema) {
  if (tema.modo === "light" || tema.modo === "dark") raiz.dataset.theme = tema.modo;
  else delete raiz.dataset.theme;
  if (tema.cor === "azul" || tema.cor === "roxo") raiz.dataset.accent = tema.cor;
  else delete raiz.dataset.accent;

  const modo = tema.modo === "light" || tema.modo === "dark" ? tema.modo : "auto";
  const cor = tema.cor === "azul" || tema.cor === "roxo" ? tema.cor : "verde";
  document.querySelectorAll("[data-modo]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.modo === modo)));
  document.querySelectorAll("[data-cor]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.cor === cor)));
}

const botaoTema = document.querySelector("[data-tema-toggle]");
const painelTema = document.getElementById("painel-tema");
if (botaoTema && painelTema) {
  let tema = lerTema();
  aplicarTema(tema);

  const abrir = (sim) => {
    painelTema.hidden = !sim;
    botaoTema.setAttribute("aria-expanded", String(sim));
  };
  botaoTema.addEventListener("click", (e) => { e.stopPropagation(); abrir(painelTema.hidden); });
  painelTema.addEventListener("click", (e) => {
    const botao = e.target.closest("button");
    if (!botao) return;
    if (botao.dataset.modo) tema = { ...tema, modo: botao.dataset.modo };
    if (botao.dataset.cor) tema = { ...tema, cor: botao.dataset.cor };
    aplicarTema(tema);
    salvarTema(tema);
  });
  document.addEventListener("click", (e) => {
    if (!painelTema.hidden && !painelTema.contains(e.target)) abrir(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !painelTema.hidden) { abrir(false); botaoTema.focus(); }
  });
}

/* ------------------------------------------------------- diálogo do "+" */
const dialogo = document.getElementById("dialogo-receita");
if (dialogo && typeof dialogo.showModal === "function") {
  document.querySelectorAll("[data-abrir-receita]").forEach((botao) =>
    botao.addEventListener("click", () => {
      dialogo.showModal();
      dialogo.querySelector('input[name="descricao"]').focus();
    }));
  dialogo.querySelector("[data-fechar]").addEventListener("click", () => dialogo.close());
  // clique no fundo escuro fecha (o preenchimento fica no .dialogo-corpo)
  dialogo.addEventListener("click", (e) => { if (e.target === dialogo) dialogo.close(); });
}

/* ------------------------------------- excluir: "só este" ou "este e os seguintes" */
const dialogoExcluir = document.getElementById("dialogo-excluir");
if (dialogoExcluir) {
  const texto = dialogoExcluir.querySelector("[data-excluir-texto]");
  const soEste = dialogoExcluir.querySelector("[data-excluir-um]");
  const seguintes = dialogoExcluir.querySelector("[data-excluir-seguintes]");

  document.querySelectorAll("[data-excluir-rec]").forEach((botao) =>
    botao.addEventListener("click", () => {
      const depois = Number(botao.dataset.qtd) - 1;   // qtd inclui o próprio item
      texto.textContent = `"${botao.dataset.titulo}" faz parte de uma recorrência. O que você quer excluir?`;
      soEste.formAction = botao.dataset.urlUm;
      seguintes.formAction = botao.dataset.urlSeguintes;
      seguintes.textContent = depois === 1 ? "Este e o seguinte" : `Este e os ${depois} seguintes`;
      dialogoExcluir.showModal();
    }));
  dialogoExcluir.querySelector("[data-fechar]").addEventListener("click", () => dialogoExcluir.close());
  dialogoExcluir.addEventListener("click", (e) => { if (e.target === dialogoExcluir) dialogoExcluir.close(); });
}

/* --------------------------------------------------------------- quinzena */
document.querySelectorAll("[data-quinzena]").forEach((bloco) => {
  const form = bloco.closest("form");
  const toggle = bloco.querySelector("[data-quinzena-toggle]");
  const campos = bloco.querySelector("[data-quinzena-campos]");
  const dia2 = bloco.querySelector('input[name="dia2"]');
  const data = form.querySelector('input[name="data"]');

  // Sugere o 2º dia 15 dias depois do 1º (dia 5 -> 20; dia 20 -> 5), até o usuário mexer.
  function sugerir() {
    if (dia2.dataset.tocado) return;
    const dia = Number(data.value.split("-")[2]);
    if (dia) dia2.value = dia + 15 <= 31 ? dia + 15 : dia - 15;
  }

  toggle.addEventListener("change", () => {
    campos.hidden = !toggle.checked;
    dia2.required = toggle.checked;
    sugerir();
  });
  data.addEventListener("change", sugerir);
  dia2.addEventListener("input", () => { dia2.dataset.tocado = "1"; });
});

/* ------------------------------------------------------------ recorrência */
document.querySelectorAll("[data-recorrencia]").forEach((bloco) => {
  const form = bloco.closest("form");
  const toggle = bloco.querySelector("[data-rec-toggle]");
  const painel = bloco.querySelector("[data-rec-meses]");
  const chips = bloco.querySelector("[data-rec-chips]");
  const campoData = form.querySelector('input[name="data"]');

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

      const label = document.createElement("label");
      label.className = "chip";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "meses";
      input.value = valor;
      input.checked = true;
      const texto = document.createElement("span");
      texto.textContent = `${ABREV[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`;
      label.append(input, texto);
      chips.append(label);
    }
  }

  toggle.addEventListener("change", () => { painel.hidden = !toggle.checked; });
  campoData.addEventListener("change", montarChips);
  bloco.querySelector("[data-rec-todos]").addEventListener("click", () => marcarTodos(true));
  bloco.querySelector("[data-rec-limpar]").addEventListener("click", () => marcarTodos(false));
});
