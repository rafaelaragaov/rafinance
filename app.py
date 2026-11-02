"""RaFinance - gestão financeira simples (Flask + SQLite)."""

import os
import sqlite3
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlsplit

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CATEGORIAS = [
    "Alimentação",
    "Transporte",
    "Moradia",
    "Contas",
    "Saúde",
    "Educação",
    "Lazer",
    "Compras",
    "Outros",
]

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
MESES_ABREV = [
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
]
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

MAX_MESES_RECORRENCIA = 24

SCHEMA = """
CREATE TABLE IF NOT EXISTS gastos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    descricao      TEXT    NOT NULL,
    valor_centavos INTEGER NOT NULL CHECK (valor_centavos > 0),
    categoria      TEXT    NOT NULL,
    data           TEXT    NOT NULL,
    recorrencia_id TEXT,
    criado_em      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_gastos_data ON gastos (data);

CREATE TABLE IF NOT EXISTS receitas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    descricao      TEXT    NOT NULL,
    valor_centavos INTEGER NOT NULL CHECK (valor_centavos > 0),
    data           TEXT    NOT NULL,
    recorrencia_id TEXT,
    criado_em      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_receitas_data ON receitas (data);
"""

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("RAFINANCE_SECRET", "rafinance-dev")
app.config["DATABASE"] = os.environ.get(
    "RAFINANCE_DB", os.path.join(BASE_DIR, "rafinance.db")
)


# --------------------------------------------------------------------------
# Banco de dados
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.executescript(SCHEMA)
    # Migração: bancos criados na v0.1 não têm a coluna recorrencia_id.
    colunas = [linha[1] for linha in db.execute("PRAGMA table_info(gastos)")]
    if "recorrencia_id" not in colunas:
        db.execute("ALTER TABLE gastos ADD COLUMN recorrencia_id TEXT")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_gastos_recorrencia ON gastos (recorrencia_id)"
    )
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------
def parse_valor(texto):
    """Converte '12,50' / '1.234,56' / '12.50' em centavos (int). None se inválido."""
    s = (texto or "").replace("R$", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(s)
    except InvalidOperation:
        return None
    centavos = int((valor * 100).to_integral_value(rounding=ROUND_HALF_UP))
    return centavos if centavos > 0 else None


@app.template_filter("brl")
def brl(centavos):
    centavos = int(centavos or 0)
    reais, cent = divmod(abs(centavos), 100)
    texto = f"{reais:,}".replace(",", ".")
    sinal = "-" if centavos < 0 else ""
    return f"{sinal}R$ {texto},{cent:02d}"


@app.template_filter("data_curta")
def data_curta(iso):
    d = date.fromisoformat(iso)
    return f"{DIAS_SEMANA[d.weekday()]}, {d.day:02d}/{d.month:02d}"


def ultimo_dia_do_mes(d):
    primeiro_prox = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return primeiro_prox - timedelta(days=1)


def vencimento(ano, mes, dia):
    """Data do gasto em ano/mês; em meses mais curtos usa o último dia (31 -> 28)."""
    ultimo = ultimo_dia_do_mes(date(ano, mes, 1)).day
    return date(ano, mes, min(dia, ultimo))


def meses_a_partir(data, quantidade=12):
    """Os próximos `quantidade` meses (a partir do mês de `data`) para o seletor."""
    opcoes = []
    ano, mes = data.year, data.month
    for _ in range(quantidade):
        opcoes.append(
            {"valor": f"{ano:04d}-{mes:02d}", "rotulo": f"{MESES_ABREV[mes - 1]}/{ano % 100:02d}"}
        )
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return opcoes


def ler_meses(valores):
    """Converte ['2026-11', ...] em [(2026, 11), ...] ordenado, sem repetidos/inválidos."""
    meses = set()
    for texto in valores:
        try:
            ano, mes = (int(x) for x in texto.split("-"))
            date(ano, mes, 1)
        except ValueError:
            continue
        if 2000 <= ano <= 2100:
            meses.add((ano, mes))
    return sorted(meses)[:MAX_MESES_RECORRENCIA]


def destino_seguro(valor, padrao):
    """Só aceita caminhos internos (/algo) no campo `next`, nunca outro site."""
    if valor and valor.startswith("/") and not valor.startswith("//") and "\\" not in valor:
        return valor
    return padrao


@app.before_request
def bloquear_envio_de_outro_site():
    """Recusa POST que o navegador marca como vindo de outro site.

    Sem isso, qualquer página aberta em outra aba poderia enviar um formulário
    para este endereço local (ex.: o "Limpar tudo") sem você perceber.
    """
    if request.method != "POST":
        return
    origem = request.headers.get("Origin")
    if origem and origem != "null" and urlsplit(origem).netloc != request.host:
        abort(403)
    if origem == "null" or request.headers.get("Sec-Fetch-Site") == "cross-site":
        abort(403)


@app.context_processor
def globais():
    """Disponível em todos os templates (o diálogo do + vive no base.html)."""
    hoje = date.today()
    return {"hoje_g": hoje, "meses_g": meses_a_partir(hoje)}


def total_periodo(db, inicio, fim, tabela="gastos"):
    assert tabela in ("gastos", "receitas")  # nome vem do código, nunca do usuário
    row = db.execute(
        f"SELECT COALESCE(SUM(valor_centavos), 0) AS total "
        f"FROM {tabela} WHERE data BETWEEN ? AND ?",
        (inicio.isoformat(), fim.isoformat()),
    ).fetchone()
    return row["total"]


def anexar_seguintes(db, tabela, linhas):
    """Linhas como dicts + `n_seguintes`: quantos lançamentos do mesmo grupo de
    recorrência têm data igual ou posterior à do item (contando o próprio).
    É o número de itens que "excluir este e os seguintes" apagaria."""
    assert tabela in ("gastos", "receitas")
    itens = [dict(linha) for linha in linhas]
    datas = {}
    for grupo in {i["recorrencia_id"] for i in itens if i["recorrencia_id"]}:
        datas[grupo] = [
            r["data"]
            for r in db.execute(
                f"SELECT data FROM {tabela} WHERE recorrencia_id = ?", (grupo,)
            )
        ]
    for i in itens:
        i["n_seguintes"] = sum(1 for d in datas.get(i["recorrencia_id"], []) if d >= i["data"])
    return itens


def ler_recorrencia_na_edicao(data_nova):
    """Meses pedidos ao marcar 'Recorrência' ao editar um lançamento avulso.

    Retorna (meses extras, erro). O mês do próprio lançamento fica de fora,
    porque ele já existe: só os outros meses ganham uma cópia.
    """
    if not request.form.get("recorrencia"):
        return [], None
    meses = ler_meses(request.form.getlist("meses"))
    if not meses:
        return [], "Recorrência: marque pelo menos um mês."
    return [m for m in meses if m != (data_nova.year, data_nova.month)], None


def ler_receita_basica():
    """Descrição, valor e data de uma receita. Retorna ((descricao, valor, date), erro)."""
    descricao = request.form.get("descricao", "").strip()
    valor = parse_valor(request.form.get("valor"))
    try:
        data = date.fromisoformat(request.form.get("data", ""))
    except ValueError:
        data = date.today()
    if not descricao:
        return None, "Informe uma descrição."
    if valor is None:
        return None, "Informe um valor válido (ex.: 3.500,00)."
    return (descricao, valor, data), None


def ler_formulario():
    """Valida o formulário de gasto. Retorna (dados, erro)."""
    descricao = request.form.get("descricao", "").strip()
    valor = parse_valor(request.form.get("valor"))
    categoria = request.form.get("categoria", "Outros")
    if categoria not in CATEGORIAS:
        categoria = "Outros"
    try:
        data = date.fromisoformat(request.form.get("data", ""))
    except ValueError:
        data = date.today()

    if not descricao:
        return None, "Informe uma descrição."
    if valor is None:
        return None, "Informe um valor válido (ex.: 12,50)."
    return (descricao, valor, categoria, data.isoformat()), None


# --------------------------------------------------------------------------
# Telas
# --------------------------------------------------------------------------
@app.route("/")
def resumo():
    db = get_db()
    hoje = date.today()

    inicio_semana = hoje - timedelta(days=hoje.weekday())  # segunda-feira
    fim_semana = inicio_semana + timedelta(days=6)
    inicio_mes = hoje.replace(day=1)
    fim_mes = ultimo_dia_do_mes(hoje)

    # Totais = o que já foi gasto (até hoje). O que ainda vai vencer aparece em "A vencer".
    total_hoje = total_periodo(db, hoje, hoje)
    total_semana = total_periodo(db, inicio_semana, hoje)
    total_mes = total_periodo(db, inicio_mes, hoje)
    media_diaria = total_mes // hoje.day

    # Últimos 7 dias (barras)
    dias = [hoje - timedelta(days=i) for i in range(6, -1, -1)]
    linhas = db.execute(
        "SELECT data, SUM(valor_centavos) AS total FROM gastos "
        "WHERE data BETWEEN ? AND ? GROUP BY data",
        (dias[0].isoformat(), dias[-1].isoformat()),
    ).fetchall()
    por_dia = {r["data"]: r["total"] for r in linhas}
    maior = max(por_dia.values(), default=0)
    grafico = [
        {
            "rotulo": DIAS_SEMANA[d.weekday()],
            "total": por_dia.get(d.isoformat(), 0),
            "pct": round(por_dia.get(d.isoformat(), 0) / maior * 100) if maior else 0,
            "hoje": d == hoje,
        }
        for d in dias
    ]

    # Categorias do mês
    categorias = [
        {
            "nome": r["categoria"],
            "total": r["total"],
            "pct": round(r["total"] / total_mes * 100) if total_mes else 0,
        }
        for r in db.execute(
            "SELECT categoria, SUM(valor_centavos) AS total FROM gastos "
            "WHERE data BETWEEN ? AND ? GROUP BY categoria ORDER BY total DESC",
            (inicio_mes.isoformat(), hoje.isoformat()),
        )
    ]

    recentes = db.execute(
        "SELECT * FROM gastos WHERE data <= ? ORDER BY data DESC, id DESC LIMIT 5",
        (hoje.isoformat(),),
    ).fetchall()

    a_vencer = db.execute(
        "SELECT * FROM gastos WHERE data > ? AND data <= ? ORDER BY data, id",
        (hoje.isoformat(), fim_mes.isoformat()),
    ).fetchall()
    total_a_vencer = sum(g_["valor_centavos"] for g_ in a_vencer)

    # Saldo: "atual" = o que já aconteceu até hoje; "previsto" = mês inteiro.
    receita_recebida = total_periodo(db, inicio_mes, hoje, "receitas")
    receita_prevista = total_periodo(db, inicio_mes, fim_mes, "receitas")
    a_receber = receita_prevista - receita_recebida
    saldo_atual = receita_recebida - total_mes
    saldo_previsto = receita_prevista - (total_mes + total_a_vencer)
    qtd_gastos = db.execute("SELECT COUNT(*) FROM gastos").fetchone()[0]
    qtd_receitas = db.execute("SELECT COUNT(*) FROM receitas").fetchone()[0]

    return render_template(
        "resumo.html",
        hoje=hoje,
        total_hoje=total_hoje,
        total_semana=total_semana,
        total_mes=total_mes,
        media_diaria=media_diaria,
        semana_label=f"{inicio_semana.day:02d}/{inicio_semana.month:02d} a "
                     f"{fim_semana.day:02d}/{fim_semana.month:02d}",
        mes_label=f"{MESES[hoje.month - 1]} de {hoje.year}",
        grafico=grafico,
        categorias=categorias,
        recentes=recentes,
        a_vencer=a_vencer,
        total_a_vencer=total_a_vencer,
        receita_recebida=receita_recebida,
        a_receber=a_receber,
        tem_receitas=receita_prevista > 0,
        saldo_atual=saldo_atual,
        saldo_previsto=saldo_previsto,
        qtd_gastos=qtd_gastos,
        qtd_receitas=qtd_receitas,
        categorias_form=CATEGORIAS,
    )


@app.route("/gastos", methods=["POST"])
def adicionar():
    destino = destino_seguro(request.form.get("next"), url_for("resumo"))
    dados, erro = ler_formulario()
    if erro:
        flash(erro, "erro")
        return redirect(destino)

    descricao, valor, categoria, data_iso = dados
    db = get_db()

    if request.form.get("recorrencia"):
        meses = ler_meses(request.form.getlist("meses"))
        if not meses:
            flash("Recorrência: marque pelo menos um mês.", "erro")
            return redirect(destino)
        dia = date.fromisoformat(data_iso).day
        grupo = uuid.uuid4().hex
        for ano, mes in meses:
            db.execute(
                "INSERT INTO gastos (descricao, valor_centavos, categoria, data, recorrencia_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (descricao, valor, categoria, vencimento(ano, mes, dia).isoformat(), grupo),
            )
        db.commit()
        flash(f"Gasto recorrente registrado em {len(meses)} mês(es).", "ok")
    else:
        db.execute(
            "INSERT INTO gastos (descricao, valor_centavos, categoria, data) "
            "VALUES (?, ?, ?, ?)",
            (descricao, valor, categoria, data_iso),
        )
        db.commit()
        flash("Gasto registrado.", "ok")
    return redirect(destino)


@app.route("/lancamentos")
def lancamentos():
    hoje = date.today()
    try:
        ano, mes = (int(x) for x in request.args.get("mes", "").split("-"))
        inicio = date(ano, mes, 1)
    except ValueError:
        inicio = hoje.replace(day=1)
    fim = ultimo_dia_do_mes(inicio)

    db = get_db()
    gastos = anexar_seguintes(db, "gastos", db.execute(
        "SELECT * FROM gastos WHERE data BETWEEN ? AND ? ORDER BY data DESC, id DESC",
        (inicio.isoformat(), fim.isoformat()),
    ).fetchall())
    total = sum(g_["valor_centavos"] for g_ in gastos)
    a_vencer_total = sum(
        g_["valor_centavos"] for g_ in gastos if g_["data"] > hoje.isoformat()
    )

    receitas = anexar_seguintes(db, "receitas", db.execute(
        "SELECT * FROM receitas WHERE data BETWEEN ? AND ? ORDER BY data DESC, id DESC",
        (inicio.isoformat(), fim.isoformat()),
    ).fetchall())
    receitas_total = sum(r_["valor_centavos"] for r_ in receitas)

    anterior = (inicio - timedelta(days=1)).replace(day=1)
    proximo = fim + timedelta(days=1)

    return render_template(
        "lancamentos.html",
        gastos=gastos,
        total=total,
        receitas=receitas,
        receitas_total=receitas_total,
        mes_label=f"{MESES[inicio.month - 1]} de {inicio.year}",
        mes_anterior=anterior.strftime("%Y-%m"),
        mes_proximo=proximo.strftime("%Y-%m"),
        mes_atual=inicio.strftime("%Y-%m"),
        categorias_form=CATEGORIAS,
        hoje=hoje,
        hoje_iso=hoje.isoformat(),
        a_vencer_total=a_vencer_total,
    )


@app.route("/gastos/<int:gasto_id>/editar", methods=["GET", "POST"])
def editar(gasto_id):
    db = get_db()
    gasto = db.execute("SELECT * FROM gastos WHERE id = ?", (gasto_id,)).fetchone()
    if gasto is None:
        abort(404)

    if request.method == "POST":
        dados, erro = ler_formulario()
        extras = []
        # Só lançamentos avulsos podem virar recorrentes (os demais já têm grupo).
        if not erro and not gasto["recorrencia_id"]:
            extras, erro = ler_recorrencia_na_edicao(date.fromisoformat(dados[3]))
        if erro:
            flash(erro, "erro")
        else:
            descricao, valor, categoria, data_iso = dados
            grupo = uuid.uuid4().hex if extras else None
            db.execute(
                "UPDATE gastos SET descricao = ?, valor_centavos = ?, categoria = ?, "
                "data = ?, recorrencia_id = COALESCE(?, recorrencia_id) WHERE id = ?",
                (descricao, valor, categoria, data_iso, grupo, gasto_id),
            )
            dia = date.fromisoformat(data_iso).day
            for ano, mes in extras:
                db.execute(
                    "INSERT INTO gastos (descricao, valor_centavos, categoria, data, recorrencia_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (descricao, valor, categoria, vencimento(ano, mes, dia).isoformat(), grupo),
                )
            db.commit()
            flash(
                f"Gasto atualizado e repetido em mais {len(extras)} mês(es)."
                if extras else "Gasto atualizado.",
                "ok",
            )
            return redirect(url_for("lancamentos", mes=data_iso[:7]))

    return render_template(
        "editar.html",
        gasto=gasto,
        categorias_form=CATEGORIAS,
        meses_edicao=meses_a_partir(date.fromisoformat(gasto["data"])),
    )


@app.route("/gastos/<int:gasto_id>/excluir", methods=["POST"])
def excluir(gasto_id):
    db = get_db()
    db.execute("DELETE FROM gastos WHERE id = ?", (gasto_id,))
    db.commit()
    flash("Gasto excluído.", "ok")
    return redirect(destino_seguro(request.form.get("next"), url_for("lancamentos")))


@app.route("/gastos/<int:gasto_id>/excluir-proximos", methods=["POST"])
def excluir_proximos(gasto_id):
    """Exclui este gasto recorrente e os dos meses seguintes (os anteriores ficam)."""
    db = get_db()
    gasto = db.execute("SELECT * FROM gastos WHERE id = ?", (gasto_id,)).fetchone()
    if gasto is None:
        abort(404)
    if gasto["recorrencia_id"]:
        cur = db.execute(
            "DELETE FROM gastos WHERE recorrencia_id = ? AND data >= ?",
            (gasto["recorrencia_id"], gasto["data"]),
        )
        db.commit()
        flash(f"{cur.rowcount} gasto(s) da recorrência excluído(s).", "ok")
    return redirect(destino_seguro(request.form.get("next"), url_for("lancamentos")))


# --------------------------------------------------------------------------
# Receitas (botão +)
# --------------------------------------------------------------------------
@app.route("/receitas", methods=["POST"])
def adicionar_receita():
    destino = destino_seguro(request.form.get("next"), url_for("resumo"))
    dados, erro = ler_receita_basica()
    if erro:
        flash(erro, "erro")
        return redirect(destino)
    descricao, valor, data = dados

    # Quinzenal: dois recebimentos por mês (o 1º no dia da data, o 2º em `dia2`).
    quinzenal = bool(request.form.get("quinzenal"))
    dia2 = valor2 = None
    if quinzenal:
        try:
            dia2 = int(request.form.get("dia2", ""))
        except ValueError:
            dia2 = None
        if dia2 is None or not 1 <= dia2 <= 31:
            flash("Quinzenal: informe o dia do 2º recebimento (1 a 31).", "erro")
            return redirect(destino)
        if dia2 == data.day:
            flash("Quinzenal: escolha dois dias diferentes no mês.", "erro")
            return redirect(destino)
        texto2 = request.form.get("valor2", "").strip()
        valor2 = parse_valor(texto2) if texto2 else valor
        if valor2 is None:
            flash("Quinzenal: valor do 2º recebimento inválido.", "erro")
            return redirect(destino)

    recorrente = bool(request.form.get("recorrencia"))
    if recorrente:
        meses = ler_meses(request.form.getlist("meses"))
        if not meses:
            flash("Recorrência: marque pelo menos um mês.", "erro")
            return redirect(destino)
    else:
        meses = [(data.year, data.month)]

    grupo = uuid.uuid4().hex if recorrente else None
    itens = []
    for ano, mes in meses:
        itens.append((vencimento(ano, mes, data.day), valor))
        if quinzenal:
            itens.append((vencimento(ano, mes, dia2), valor2))

    db = get_db()
    for dia, centavos in itens:
        db.execute(
            "INSERT INTO receitas (descricao, valor_centavos, data, recorrencia_id) "
            "VALUES (?, ?, ?, ?)",
            (descricao, centavos, dia.isoformat(), grupo),
        )
    db.commit()
    flash(
        "Receita registrada." if len(itens) == 1 else f"{len(itens)} receitas registradas.",
        "ok",
    )
    return redirect(destino)


@app.route("/receitas/<int:receita_id>/editar", methods=["GET", "POST"])
def editar_receita(receita_id):
    db = get_db()
    receita = db.execute("SELECT * FROM receitas WHERE id = ?", (receita_id,)).fetchone()
    if receita is None:
        abort(404)

    if request.method == "POST":
        dados, erro = ler_receita_basica()
        extras = []
        if not erro and not receita["recorrencia_id"]:
            extras, erro = ler_recorrencia_na_edicao(dados[2])
        if erro:
            flash(erro, "erro")
        else:
            descricao, valor, data = dados
            grupo = uuid.uuid4().hex if extras else None
            db.execute(
                "UPDATE receitas SET descricao = ?, valor_centavos = ?, data = ?, "
                "recorrencia_id = COALESCE(?, recorrencia_id) WHERE id = ?",
                (descricao, valor, data.isoformat(), grupo, receita_id),
            )
            for ano, mes in extras:
                db.execute(
                    "INSERT INTO receitas (descricao, valor_centavos, data, recorrencia_id) "
                    "VALUES (?, ?, ?, ?)",
                    (descricao, valor, vencimento(ano, mes, data.day).isoformat(), grupo),
                )
            db.commit()
            flash(
                f"Receita atualizada e repetida em mais {len(extras)} mês(es)."
                if extras else "Receita atualizada.",
                "ok",
            )
            return redirect(url_for("lancamentos", mes=data.isoformat()[:7]))

    return render_template(
        "editar_receita.html",
        receita=receita,
        meses_edicao=meses_a_partir(date.fromisoformat(receita["data"])),
    )


@app.route("/receitas/<int:receita_id>/excluir", methods=["POST"])
def excluir_receita(receita_id):
    db = get_db()
    db.execute("DELETE FROM receitas WHERE id = ?", (receita_id,))
    db.commit()
    flash("Receita excluída.", "ok")
    return redirect(destino_seguro(request.form.get("next"), url_for("lancamentos")))


@app.route("/receitas/<int:receita_id>/excluir-proximos", methods=["POST"])
def excluir_proximos_receita(receita_id):
    """Exclui esta receita recorrente e as dos meses seguintes (as anteriores ficam)."""
    db = get_db()
    receita = db.execute("SELECT * FROM receitas WHERE id = ?", (receita_id,)).fetchone()
    if receita is None:
        abort(404)
    if receita["recorrencia_id"]:
        cur = db.execute(
            "DELETE FROM receitas WHERE recorrencia_id = ? AND data >= ?",
            (receita["recorrencia_id"], receita["data"]),
        )
        db.commit()
        flash(f"{cur.rowcount} receita(s) da recorrência excluída(s).", "ok")
    return redirect(destino_seguro(request.form.get("next"), url_for("lancamentos")))


@app.route("/limpar-tudo", methods=["POST"])
def limpar_tudo():
    """Apaga todos os gastos e todas as receitas. Não há como desfazer."""
    db = get_db()
    gastos = db.execute("SELECT COUNT(*) FROM gastos").fetchone()[0]
    receitas = db.execute("SELECT COUNT(*) FROM receitas").fetchone()[0]
    db.execute("DELETE FROM gastos")
    db.execute("DELETE FROM receitas")
    db.commit()
    flash(f"Tudo limpo: {gastos} gasto(s) e {receitas} receita(s) apagados.", "ok")
    return redirect(url_for("resumo"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
