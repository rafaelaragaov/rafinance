# RaFinance

Gestão financeira pessoal, simples e minimalista. Registre seus gastos em segundos e veja
na hora quanto gastou **hoje**, **nesta semana** e **neste mês**.

> Protótipo v0.4 — em desenvolvimento.

## Telas

| Tela | O que faz |
|------|-----------|
| **Resumo** | **Saldo atual** com a **fatura do mês** (total, já pago, falta pagar), totais de hoje / semana / mês, formulário rápido de novo gasto, gráfico dos últimos 7 dias e gastos por categoria |
| **Lançamentos** | Gastos e receitas por mês (navegação ← →), com **checkbox de pago**, editar e excluir |
| **Editar** | Corrige um gasto ou uma receita |

Em todas as telas, o topo tem dois ícones: **+** (adicionar saldo) e **◐** (aparência).

### Saldo atual, fatura e pago / não pago

No topo do **Resumo** fica o módulo de saldo:

- **Saldo atual** = tudo o que você já recebeu (receitas até hoje) − tudo o que você já **marcou como
  pago**. Gasto não pago ainda não sai do saldo.
- **+ Adicionar saldo** registra uma receita (salário, freelance ou o saldo que você já tem, com a
  data de hoje).
- **Fatura do mês**: *total*, *já pago* e *falta pagar*, com barra de progresso. Quando tudo está
  pago aparece **Quitada**. O app também diz quanto sobra depois de pagar o que falta — ou quanto
  o saldo não cobre.
- Cada gasto tem um **checkbox**: na lista "falta pagar" do Resumo e em **Lançamentos**. Marcar ou
  desmarcar salva na hora. Os já pagos ficam recolhidos em "Já pagos".
- Gasto novo nasce **não pago**; marque **Já paguei** no formulário se já pagou. Numa recorrência,
  "Já paguei" vale só para o mês da data escolhida.
- Bancos antigos são migrados: gastos de meses anteriores ficam como **pagos** (histórico) e os do
  mês atual em diante como **não pagos**.

Os cartões Hoje / Semana / Mês continuam somando o que foi registrado até a data, pago ou não.

### Receitas (botão +)

O **+** abre o formulário de **Adicionar saldo** (receita). Quem recebe por quinzena marca
**Quinzenal**: informa o dia do 2º recebimento (e, se for diferente, o valor do 2º) e o RaFinance
cria **dois recebimentos por mês**. Combinado com **Recorrência**, cria os dois recebimentos em
cada mês escolhido (ex.: dia 5 e dia 20, de novembro a abril).

Receitas com data futura não entram no saldo atual; aparecem como "ainda a receber neste mês".

### Excluir e limpar

- Em **Lançamentos**, **excluir** um item que faz parte de uma recorrência abre uma janela com
  **Só este** e **Este e os N seguintes** (mantém os meses anteriores). Itens avulsos, ou o último
  da recorrência, têm o excluir comum com confirmação.
- No topo do **Resumo**, o botão **Limpar tudo** apaga todos os gastos e receitas, depois de uma
  confirmação que mostra quantos itens serão excluídos. Não há como desfazer.
- Os formulários só aceitam envio vindo do próprio site (checagem de `Origin`), para que uma
  página aberta em outra aba não consiga acionar, por exemplo, o "Limpar tudo".

### Aparência

O ícone **◐** abre um painel minimalista com:

- **Modo:** Claro, Escuro ou Auto (segue o sistema);
- **Cor:** 3 paletas prontas — verde (padrão), azul e roxo.

A escolha fica salva no navegador. O CSS usa variáveis com `light-dark()`, então uma única
definição de cor serve para os dois modos.

### Recorrência (gastos que se repetem todo mês)

No formulário **Novo gasto**, marque **Recorrência** (seguro do carro, aluguel, assinaturas...).
Aparecem 12 meses a partir da data escolhida; marque os meses desejados e o RaFinance cria um
gasto em cada um, **no mesmo dia** (em meses mais curtos, no último dia: 31 → 28/30).

- Os cartões de hoje/semana/mês contam só o que já tem data até hoje; os gastos que ainda vão
  vencer neste mês entram na **fatura do mês** (marcados "a vencer" em Lançamentos).
- Na tela Lançamentos, itens recorrentes têm o selo `recorrente` e o botão **excluir próximos**
  (apaga aquele mês e os seguintes, mantendo os anteriores).
- **Dá para tornar recorrente um lançamento que já existe:** em Lançamentos, clique em **editar**,
  marque **Recorrência** e escolha os meses. O lançamento atual fica como está e o app cria uma
  cópia em cada um dos outros meses marcados (vale para gastos e receitas). Quem já é recorrente
  mostra um aviso no lugar do checkbox.
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
│   └── app.js          # tema, diálogo do +, quinzena e recorrência
├── templates/          # base, resumo, lançamentos, editar (gasto e receita) e partials _form_*
└── tests/test_app.py
```

## Roadmap

- [x] Receitas (botão +, quinzenal)
- [x] Saldo atual, fatura do mês e checkbox pago / não pago
- [x] Temas: modo claro/escuro e 3 cores
- [ ] Metas / orçamento por categoria
- [x] Gastos recorrentes (checkbox Recorrência + seleção de meses)
- [ ] Editar uma recorrência inteira de uma vez (hoje só dá para excluir "daqui para frente")
- [ ] Exportar para CSV
- [ ] Login e uso em mais de um dispositivo
