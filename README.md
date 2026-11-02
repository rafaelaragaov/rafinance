# RaFinance

Gestão financeira pessoal, simples e minimalista. Registre seus gastos em segundos e veja
na hora quanto gastou **hoje**, **nesta semana** e **neste mês**.

> Protótipo v0.2 — em desenvolvimento.

## Telas

| Tela | O que faz |
|------|-----------|
| **Resumo** | Totais de hoje / semana / mês, média diária, gráfico dos últimos 7 dias, gastos por categoria, bloco "A vencer neste mês" e formulário rápido de novo gasto |
| **Lançamentos** | Lista de gastos por mês (navegação ← →), com editar e excluir |
| **Editar** | Corrige descrição, valor, categoria ou data de um gasto |

### Recorrência (gastos que se repetem todo mês)

No formulário **Novo gasto**, marque **Recorrência** (seguro do carro, aluguel, assinaturas...).
Aparecem 12 meses a partir da data escolhida; marque os meses desejados e o RaFinance cria um
gasto em cada um, **no mesmo dia** (em meses mais curtos, no último dia: 31 → 28/30).

- Os totais de hoje/semana/mês contam só o que **já venceu**; o que ainda vai vencer neste mês
  aparece em **A vencer neste mês**.
- Na tela Lançamentos, itens recorrentes têm o selo `recorrente` e o botão **excluir próximos**
  (apaga aquele mês e os seguintes, mantendo os anteriores).
- Bancos criados na v0.1 são migrados automaticamente ao abrir o app.

## Tecnologias

- **Python 3** + **Flask**
- **SQLite** (arquivo local `rafinance.db`, sem servidor para configurar)
- HTML (Jinja2) + CSS puro, sem JavaScript de terceiros

Valores são guardados em **centavos (inteiros)** para evitar erros de arredondamento.
A semana vai de **segunda a domingo**.

## Como rodar

```bash
git clone <url-do-repositorio>
cd rafinance

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Abra http://127.0.0.1:5000 no navegador. O banco é criado automaticamente na primeira execução.

Variáveis opcionais: `RAFINANCE_DB` (caminho do banco) e `RAFINANCE_SECRET` (chave de sessão).

## Testes

```bash
python -m unittest discover -s tests -v
```

## Estrutura

```
rafinance/
├── app.py              # rotas, regras e acesso ao banco
├── requirements.txt
├── static/
│   ├── style.css
│   └── app.js          # checkbox Recorrência e seleção de meses
├── templates/          # base, resumo, lançamentos, editar
└── tests/test_app.py
```

## Roadmap

- [ ] Receitas e saldo do mês
- [ ] Metas / orçamento por categoria
- [x] Gastos recorrentes (checkbox Recorrência + seleção de meses)
- [ ] Editar/excluir uma recorrência inteira de uma vez
- [ ] Exportar para CSV
- [ ] Login e uso em mais de um dispositivo
