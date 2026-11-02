"""RaFinance - gestão financeira simples (Flask + SQLite)."""

import os
import sqlite3
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

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
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS gastos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    descricao      TEXT    NOT NULL,
    valor_centavos INTEGER NOT NULL CHECK (valor_centavos > 0),
    categoria      TEXT    NOT NULL,
    data           TEXT    NOT NULL,
    criado_em      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_gastos_data ON gastos (data);
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


def total_periodo(db, inicio, fim):
    row = db.execute(
        "SELECT COALESCE(SUM(valor_centavos), 0) AS total "
        "FROM gastos WHERE data BETWEEN ? AND ?",
        (inicio.isoformat(), fim.isoformat()),
    ).fetchone()
    return row["total"]


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

    total_hoje = total_periodo(db, hoje, hoje)
    total_semana = total_periodo(db, inicio_semana, fim_semana)
    total_mes = total_periodo(db, inicio_mes, fim_mes)
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
            (inicio_mes.isoformat(), fim_mes.isoformat()),
        )
    ]

    recentes = db.execute(
        "SELECT * FROM gastos ORDER BY data DESC, id DESC LIMIT 5"
    ).fetchall()

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
        categorias_form=CATEGORIAS,
    )


@app.route("/gastos", methods=["POST"])
def adicionar():
    dados, erro = ler_formulario()
    if erro:
        flash(erro, "erro")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO gastos (descricao, valor_centavos, categoria, data) "
            "VALUES (?, ?, ?, ?)",
            dados,
        )
        db.commit()
        flash("Gasto registrado.", "ok")
    return redirect(request.form.get("next") or url_for("resumo"))


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
    gastos = db.execute(
        "SELECT * FROM gastos WHERE data BETWEEN ? AND ? ORDER BY data DESC, id DESC",
        (inicio.isoformat(), fim.isoformat()),
    ).fetchall()
    total = sum(g_["valor_centavos"] for g_ in gastos)

    anterior = (inicio - timedelta(days=1)).replace(day=1)
    proximo = fim + timedelta(days=1)

    return render_template(
        "lancamentos.html",
        gastos=gastos,
        total=total,
        mes_label=f"{MESES[inicio.month - 1]} de {inicio.year}",
        mes_anterior=anterior.strftime("%Y-%m"),
        mes_proximo=proximo.strftime("%Y-%m"),
        mes_atual=inicio.strftime("%Y-%m"),
        categorias_form=CATEGORIAS,
        hoje=hoje,
    )


@app.route("/gastos/<int:gasto_id>/editar", methods=["GET", "POST"])
def editar(gasto_id):
    db = get_db()
    gasto = db.execute("SELECT * FROM gastos WHERE id = ?", (gasto_id,)).fetchone()
    if gasto is None:
        abort(404)

    if request.method == "POST":
        dados, erro = ler_formulario()
        if erro:
            flash(erro, "erro")
        else:
            db.execute(
                "UPDATE gastos SET descricao = ?, valor_centavos = ?, "
                "categoria = ?, data = ? WHERE id = ?",
                (*dados, gasto_id),
            )
            db.commit()
            flash("Gasto atualizado.", "ok")
            return redirect(url_for("lancamentos", mes=dados[3][:7]))

    return render_template("editar.html", gasto=gasto, categorias_form=CATEGORIAS)


@app.route("/gastos/<int:gasto_id>/excluir", methods=["POST"])
def excluir(gasto_id):
    db = get_db()
    db.execute("DELETE FROM gastos WHERE id = ?", (gasto_id,))
    db.commit()
    flash("Gasto excluído.", "ok")
    return redirect(request.form.get("next") or url_for("lancamentos"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
