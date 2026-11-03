import os
import re
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

import app as rafinance


class RaFinanceTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        rafinance.app.config["DATABASE"] = self.db_path
        rafinance.app.config["TESTING"] = True
        rafinance.init_db()
        self.client = rafinance.app.test_client()

    def tearDown(self):
        os.unlink(self.db_path)

    def adicionar(self, descricao, valor, data, categoria="Outros", pago=False):
        dados = {
            "descricao": descricao,
            "valor": valor,
            "categoria": categoria,
            "data": data.isoformat(),
        }
        if pago:
            dados["pago"] = "1"          # checkbox "Já paguei"
        return self.client.post("/gastos", data=dados, follow_redirects=True)

    def marcar(self, gasto_id, pago=True, **extras):
        """Simula o checkbox da lista: manda um "0" fixo e, se marcado, também um "1"."""
        dados = {"pago": ["0", "1"] if pago else ["0"]}
        dados.update(extras)
        return self.client.post(f"/gastos/{gasto_id}/pago", data=dados)

    def saldo_atual(self, pagina=None):
        pagina = pagina or self.client.get("/").data.decode()
        return re.search(r'class="saldo-valor [^"]*">(-?R\$ [\d.,]+)</strong>', pagina).group(1)

    def numeros_fatura(self, pagina=None):
        """(total, pago, falta) mostrados no módulo de saldo da tela inicial."""
        pagina = pagina or self.client.get("/").data.decode()
        def valor(rotulo):
            return re.search(rf'{rotulo}</span><strong class="[^"]*">(-?R\$ [\d.,]+)</strong>',
                             pagina).group(1)
        return valor("Total da fatura"), valor("Já pago"), valor("Falta pagar")

    def cartoes(self, pagina):
        """Valores dos cartões Hoje / Esta semana / Este mês."""
        secao = re.search(r'<section class="cartoes">.*?</section>', pagina, re.S).group(0)
        return re.findall(r"<strong>(R\$ [\d.,]+)</strong>", secao)

    def test_parse_valor(self):
        self.assertEqual(rafinance.parse_valor("12,50"), 1250)
        self.assertEqual(rafinance.parse_valor("1.234,56"), 123456)
        self.assertEqual(rafinance.parse_valor("R$ 8"), 800)
        self.assertEqual(rafinance.parse_valor("7.5"), 750)
        self.assertIsNone(rafinance.parse_valor("abc"))
        self.assertIsNone(rafinance.parse_valor("0"))
        self.assertIsNone(rafinance.parse_valor("-5"))

    def test_formato_brl(self):
        self.assertEqual(rafinance.brl(123456), "R$ 1.234,56")
        self.assertEqual(rafinance.brl(5), "R$ 0,05")
        self.assertEqual(rafinance.brl(0), "R$ 0,00")

    def test_totais_diario_semanal_mensal(self):
        hoje = date.today()
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        fim_semana = inicio_semana + timedelta(days=6)
        inicio_mes = hoje.replace(day=1)
        fim_mes = rafinance.ultimo_dia_do_mes(hoje)
        mes_passado = inicio_mes - timedelta(days=1)

        # (data, centavos): o teste calcula o esperado para qualquer dia da semana
        lancamentos = [(hoje, 1000), (inicio_semana, 2000), (mes_passado, 10000)]
        for data, centavos in lancamentos:
            self.adicionar("Teste", f"{centavos // 100},00", data)

        def esperado(inicio, fim):
            return sum(c for d, c in lancamentos if inicio <= d <= fim)

        with rafinance.app.app_context():
            db = rafinance.get_db()
            self.assertEqual(rafinance.total_periodo(db, hoje, hoje), esperado(hoje, hoje))
            self.assertEqual(
                rafinance.total_periodo(db, inicio_semana, fim_semana),
                esperado(inicio_semana, fim_semana),
            )
            self.assertEqual(
                rafinance.total_periodo(db, inicio_mes, fim_mes),
                esperado(inicio_mes, fim_mes),
            )
            # o lançamento do mês passado nunca entra no total do mês atual
            self.assertNotEqual(rafinance.total_periodo(db, inicio_mes, fim_mes), 13000)

    def test_telas_carregam(self):
        self.adicionar("Café", "5,00", date.today(), "Alimentação")
        for rota in ("/", "/lancamentos", "/lancamentos?mes=2026-01"):
            resposta = self.client.get(rota)
            self.assertEqual(resposta.status_code, 200, rota)
        self.assertIn("Café".encode(), self.client.get("/").data)

    def test_validacao(self):
        resposta = self.adicionar("", "10", date.today())
        self.assertIn("Informe uma descrição".encode(), resposta.data)
        resposta = self.adicionar("X", "abc", date.today())
        self.assertIn("valor válido".encode(), resposta.data)

    def test_editar_e_excluir(self):
        self.adicionar("Errado", "10,00", date.today())
        self.client.post(
            "/gastos/1/editar",
            data={
                "descricao": "Certo",
                "valor": "15,00",
                "categoria": "Lazer",
                "data": date.today().isoformat(),
            },
        )
        self.assertIn("Certo".encode(), self.client.get("/lancamentos").data)
        self.client.post("/gastos/1/excluir")
        self.assertNotIn("Certo".encode(), self.client.get("/lancamentos").data)
        self.assertEqual(self.client.get("/gastos/99/editar").status_code, 404)

    # ---------------------------------------------------------------- recorrência
    def recorrente(self, data, meses, descricao="Seguro do carro", valor="350,00"):
        return self.client.post(
            "/gastos",
            data={
                "descricao": descricao,
                "valor": valor,
                "categoria": "Contas",
                "data": data.isoformat(),
                "recorrencia": "1",
                "meses": meses,
            },
            follow_redirects=True,
        )

    def gastos_no_banco(self):
        with rafinance.app.app_context():
            db = rafinance.get_db()
            return [dict(r) for r in db.execute("SELECT * FROM gastos ORDER BY data")]

    def test_recorrencia_cria_um_gasto_por_mes_marcado(self):
        self.recorrente(date(2026, 1, 10), ["2026-01", "2026-03", "2026-04"])
        gastos = self.gastos_no_banco()
        self.assertEqual(
            [g["data"] for g in gastos], ["2026-01-10", "2026-03-10", "2026-04-10"]
        )
        self.assertEqual(len({g["recorrencia_id"] for g in gastos}), 1)
        self.assertTrue(all(g["recorrencia_id"] for g in gastos))

    def test_recorrencia_dia_31_usa_ultimo_dia_do_mes(self):
        self.recorrente(date(2026, 1, 31), ["2026-01", "2026-02", "2026-04"])
        self.assertEqual(
            [g["data"] for g in self.gastos_no_banco()],
            ["2026-01-31", "2026-02-28", "2026-04-30"],
        )

    def test_recorrencia_vira_o_ano(self):
        self.recorrente(date(2026, 11, 5), ["2026-11", "2026-12", "2027-01"])
        self.assertEqual(
            [g["data"] for g in self.gastos_no_banco()],
            ["2026-11-05", "2026-12-05", "2027-01-05"],
        )

    def test_recorrencia_sem_meses_nao_cria_nada(self):
        resposta = self.recorrente(date(2026, 1, 10), [])
        self.assertIn("marque pelo menos um mês".encode(), resposta.data)
        self.assertEqual(self.gastos_no_banco(), [])

    def test_recorrencia_ignora_meses_invalidos_e_repetidos(self):
        self.recorrente(date(2026, 1, 10), ["2026-13", "abc", "2026-02", "2026-02"])
        self.assertEqual([g["data"] for g in self.gastos_no_banco()], ["2026-02-10"])

    def test_sem_o_checkbox_cria_um_gasto_unico(self):
        self.client.post(
            "/gastos",
            data={
                "descricao": "Avulso",
                "valor": "10",
                "categoria": "Outros",
                "data": "2026-01-10",
                "meses": ["2026-01", "2026-02"],
            },
        )
        gastos = self.gastos_no_banco()
        self.assertEqual(len(gastos), 1)
        self.assertIsNone(gastos[0]["recorrencia_id"])

    def test_excluir_proximos_mantem_os_anteriores(self):
        self.recorrente(date(2026, 1, 10), ["2026-01", "2026-02", "2026-03"])
        gastos = self.gastos_no_banco()
        self.client.post(f"/gastos/{gastos[1]['id']}/excluir-proximos")
        self.assertEqual([g["data"] for g in self.gastos_no_banco()], ["2026-01-10"])

    def test_cartoes_contam_ate_hoje_mas_a_fatura_inclui_o_mes_todo(self):
        hoje = date.today()
        amanha = hoje + timedelta(days=1)
        self.adicionar("Gasto de hoje", "10,00", hoje)
        self.adicionar("Boleto de amanha", "500,00", amanha)
        pagina = self.client.get("/").data.decode()
        self.assertEqual(self.cartoes(pagina), ["R$ 10,00"] * 3)  # hoje, semana, mês
        if amanha.month == hoje.month:
            self.assertEqual(self.numeros_fatura(pagina)[0], "R$ 510,00")
            self.assertIn("Boleto de amanha", pagina)
        else:
            self.assertEqual(self.numeros_fatura(pagina)[0], "R$ 10,00")
            self.assertNotIn("Boleto de amanha", pagina)

    def test_meses_a_partir_vira_o_ano(self):
        opcoes = rafinance.meses_a_partir(date(2026, 11, 2), 4)
        self.assertEqual(
            [o["valor"] for o in opcoes], ["2026-11", "2026-12", "2027-01", "2027-02"]
        )
        self.assertEqual(opcoes[2]["rotulo"], "jan/27")

    def formulario(self, pagina, acao):
        """Trecho HTML do <form> cuja action é `acao`."""
        achado = re.search(
            rf'<form[^>]*action="{re.escape(acao)}"[^>]*>.*?</form>', pagina, re.S
        )
        self.assertIsNotNone(achado, f"form {acao} não encontrado")
        return achado.group(0)

    def test_formulario_de_criar_tem_recorrencia(self):
        pagina = self.client.get("/").data.decode()
        # gasto + diálogo de receita: cada um com seus 12 meses
        self.assertEqual(pagina.count("data-recorrencia"), 2)
        self.assertEqual(self.formulario(pagina, "/gastos").count('name="meses"'), 12)

    # --------------------------------------------- recorrência ao editar (avulso -> recorrente)
    def primeiro_gasto(self):
        with rafinance.app.app_context():
            return dict(rafinance.get_db().execute("SELECT * FROM gastos ORDER BY id").fetchone())

    def editar_gasto(self, gasto_id, **campos):
        dados = {"descricao": "Seguro", "valor": "350,00", "categoria": "Contas",
                 "data": "2026-03-10"}
        dados.update(campos)
        return self.client.post(f"/gastos/{gasto_id}/editar", data=dados, follow_redirects=True)

    def test_editar_gasto_avulso_oferece_recorrencia_a_partir_do_mes_dele(self):
        self.adicionar("Seguro", "350,00", date(2026, 3, 10), "Contas")
        edicao = self.client.get("/gastos/1/editar").data.decode()
        form = self.formulario(edicao, "/gastos/1/editar")
        self.assertIn("data-recorrencia", form)
        self.assertEqual(re.findall(r'name="meses" value="([\d-]+)"', form)[:3],
                         ["2026-03", "2026-04", "2026-05"])
        # o diálogo do + continua começando em hoje, não no mês do lançamento
        dialogo = self.formulario(edicao, "/receitas")
        self.assertEqual(re.findall(r'name="meses" value="([\d-]+)"', dialogo)[0],
                         date.today().strftime("%Y-%m"))

    def test_editar_gasto_marcando_recorrencia_cria_copias_e_mantem_o_original(self):
        self.adicionar("Seguro", "350,00", date(2026, 3, 10), "Contas")
        resposta = self.editar_gasto(1, recorrencia="1",
                                     meses=["2026-03", "2026-04", "2026-06"])
        self.assertIn("repetido em mais 2 mês".encode(), resposta.data)
        gastos = self.gastos_no_banco()
        self.assertEqual([g["data"] for g in gastos], ["2026-03-10", "2026-04-10", "2026-06-10"])
        self.assertEqual(gastos[0]["id"], 1)                       # o original continua sendo o mesmo
        self.assertEqual(len({g["recorrencia_id"] for g in gastos}), 1)
        self.assertIsNotNone(gastos[0]["recorrencia_id"])
        self.assertEqual({(g["descricao"], g["valor_centavos"], g["categoria"]) for g in gastos},
                         {("Seguro", 35000, "Contas")})

    def test_editar_gasto_recorrente_aplica_as_mudancas_nas_copias(self):
        self.adicionar("Antigo", "10,00", date(2026, 3, 31), "Outros")
        self.editar_gasto(1, descricao="Novo", valor="20,00", data="2026-03-31",
                          recorrencia="1", meses=["2026-03", "2026-04"])
        gastos = self.gastos_no_banco()
        self.assertEqual([g["data"] for g in gastos], ["2026-03-31", "2026-04-30"])  # dia 31 -> 30
        self.assertEqual({g["descricao"] for g in gastos}, {"Novo"})

    def test_editar_gasto_mudando_a_data_usa_o_dia_novo_nas_copias(self):
        self.adicionar("Seguro", "350,00", date(2026, 3, 5), "Contas")
        self.editar_gasto(1, data="2026-03-12", recorrencia="1", meses=["2026-03", "2026-04"])
        self.assertEqual([g["data"] for g in self.gastos_no_banco()], ["2026-03-12", "2026-04-12"])

    def test_editar_gasto_so_com_o_proprio_mes_nao_cria_recorrencia(self):
        self.adicionar("Seguro", "350,00", date(2026, 3, 10), "Contas")
        self.editar_gasto(1, descricao="Seguro 2", recorrencia="1", meses=["2026-03"])
        [g] = self.gastos_no_banco()
        self.assertEqual(g["descricao"], "Seguro 2")
        self.assertIsNone(g["recorrencia_id"])

    def test_editar_gasto_recorrencia_sem_meses_da_erro_e_nao_altera_nada(self):
        self.adicionar("Seguro", "350,00", date(2026, 3, 10), "Contas")
        resposta = self.editar_gasto(1, descricao="Mudou", recorrencia="1")
        self.assertIn("marque pelo menos um mês".encode(), resposta.data)
        [g] = self.gastos_no_banco()
        self.assertEqual(g["descricao"], "Seguro")
        self.assertIsNone(g["recorrencia_id"])

    def test_editar_sem_marcar_recorrencia_nao_cria_copias(self):
        self.adicionar("Seguro", "350,00", date(2026, 3, 10), "Contas")
        self.editar_gasto(1, meses=["2026-03", "2026-04"])   # meses enviados, checkbox desmarcado
        self.assertEqual(len(self.gastos_no_banco()), 1)

    def test_gasto_ja_recorrente_nao_oferece_nem_aceita_nova_recorrencia(self):
        self.recorrente(date(2026, 3, 10), ["2026-03", "2026-04"])
        edicao = self.client.get("/gastos/1/editar").data.decode()
        form = self.formulario(edicao, "/gastos/1/editar")
        self.assertNotIn("data-recorrencia", form)
        self.assertIn("já faz parte de uma recorrência", form)
        self.editar_gasto(1, recorrencia="1", meses=["2026-03", "2026-05", "2026-06"])
        self.assertEqual(len(self.gastos_no_banco()), 2)       # nada foi criado

    def test_editar_receita_marcando_recorrencia(self):
        self.receita(descricao="Salário", valor="1.500,00", data=date(2026, 3, 5))
        edicao = self.client.get("/receitas/1/editar").data.decode()
        form = self.formulario(edicao, "/receitas/1/editar")
        self.assertIn("data-recorrencia", form)
        self.assertNotIn('name="quinzenal"', form)             # quinzena só ao criar
        resposta = self.client.post("/receitas/1/editar", data={
            "descricao": "Salário", "valor": "1.500,00", "data": "2026-03-05",
            "recorrencia": "1", "meses": ["2026-03", "2026-04", "2026-05"]},
            follow_redirects=True)
        self.assertIn("Receita atualizada e repetida em mais 2".encode(), resposta.data)
        receitas = self.receitas_no_banco()
        self.assertEqual([r["data"] for r in receitas], ["2026-03-05", "2026-04-05", "2026-05-05"])
        self.assertEqual(len({r["recorrencia_id"] for r in receitas}), 1)
        # agora é recorrente: o formulário mostra o aviso em vez do checkbox
        form = self.formulario(self.client.get("/receitas/1/editar").data.decode(),
                               "/receitas/1/editar")
        self.assertNotIn("data-recorrencia", form)
        self.assertIn("já faz parte de uma recorrência", form)

    def test_editar_receita_recorrencia_sem_meses_da_erro(self):
        self.receita(descricao="Salário", data=date(2026, 3, 5))
        resposta = self.client.post("/receitas/1/editar", data={
            "descricao": "Mudou", "valor": "1", "data": "2026-03-05", "recorrencia": "1"},
            follow_redirects=True)
        self.assertIn("marque pelo menos um mês".encode(), resposta.data)
        self.assertEqual(self.receitas_no_banco()[0]["descricao"], "Salário")

    # ------------------------------------------------------------------ receitas
    def receita(self, descricao="Salário", valor="1.500,00", data=None, **extras):
        dados = {"descricao": descricao, "valor": valor,
                 "data": (data or date.today()).isoformat()}
        dados.update(extras)
        return self.client.post("/receitas", data=dados, follow_redirects=True)

    def receitas_no_banco(self):
        with rafinance.app.app_context():
            db = rafinance.get_db()
            return [dict(r) for r in db.execute("SELECT * FROM receitas ORDER BY data, id")]

    def test_receita_simples(self):
        resposta = self.receita(data=date(2026, 3, 5))
        self.assertIn("Receita registrada".encode(), resposta.data)
        [r] = self.receitas_no_banco()
        self.assertEqual((r["descricao"], r["valor_centavos"], r["data"]),
                         ("Salário", 150000, "2026-03-05"))
        self.assertIsNone(r["recorrencia_id"])

    def test_receita_quinzenal_cria_dois_recebimentos_no_mes(self):
        self.receita(data=date(2026, 3, 5), quinzenal="1", dia2="20")
        self.assertEqual(
            [(r["data"], r["valor_centavos"]) for r in self.receitas_no_banco()],
            [("2026-03-05", 150000), ("2026-03-20", 150000)],
        )

    def test_receita_quinzenal_com_valor_diferente_no_segundo(self):
        self.receita(data=date(2026, 3, 5), quinzenal="1", dia2="20", valor2="900,50")
        self.assertEqual(
            [r["valor_centavos"] for r in self.receitas_no_banco()], [150000, 90050]
        )

    def test_receita_quinzenal_recorrente_cria_dois_por_mes_marcado(self):
        self.receita(data=date(2026, 1, 15), quinzenal="1", dia2="31",
                     recorrencia="1", meses=["2026-01", "2026-02", "2026-03"])
        recebimentos = self.receitas_no_banco()
        self.assertEqual(
            [r["data"] for r in recebimentos],
            ["2026-01-15", "2026-01-31", "2026-02-15", "2026-02-28",
             "2026-03-15", "2026-03-31"],  # dia 31 vira 28 em fevereiro
        )
        self.assertEqual(len({r["recorrencia_id"] for r in recebimentos}), 1)

    def test_receita_quinzenal_valida_o_segundo_dia(self):
        for extras in ({"dia2": ""}, {"dia2": "0"}, {"dia2": "32"}, {"dia2": "abc"},
                       {"dia2": "5"},                      # igual ao dia do 1º
                       {"dia2": "20", "valor2": "xx"}):    # valor inválido
            resposta = self.receita(data=date(2026, 3, 5), quinzenal="1", **extras)
            self.assertIn("Quinzenal".encode(), resposta.data, extras)
        self.assertEqual(self.receitas_no_banco(), [])

    def test_receita_sem_quinzenal_ignora_dia2(self):
        self.receita(data=date(2026, 3, 5), dia2="20")
        self.assertEqual(len(self.receitas_no_banco()), 1)

    def test_receita_valida_descricao_e_valor(self):
        self.assertIn("Informe uma descrição".encode(), self.receita(descricao="").data)
        self.assertIn("valor válido".encode(), self.receita(valor="abc").data)
        self.assertEqual(self.receitas_no_banco(), [])

    def test_receita_recorrencia_sem_meses_nao_cria_nada(self):
        resposta = self.receita(recorrencia="1")
        self.assertIn("marque pelo menos um mês".encode(), resposta.data)
        self.assertEqual(self.receitas_no_banco(), [])

    def test_editar_e_excluir_receita(self):
        self.receita(descricao="Errada", valor="10,00", data=date(2026, 3, 5))
        self.client.post("/receitas/1/editar", data={
            "descricao": "Certa", "valor": "20,00", "data": "2026-03-06"})
        [r] = self.receitas_no_banco()
        self.assertEqual((r["descricao"], r["valor_centavos"], r["data"]),
                         ("Certa", 2000, "2026-03-06"))
        self.assertEqual(self.client.get("/receitas/1/editar").status_code, 200)
        self.client.post("/receitas/1/excluir")
        self.assertEqual(self.receitas_no_banco(), [])
        self.assertEqual(self.client.get("/receitas/99/editar").status_code, 404)

    def test_excluir_proximos_receita_mantem_as_anteriores(self):
        self.receita(data=date(2026, 1, 5), recorrencia="1",
                     meses=["2026-01", "2026-02", "2026-03"])
        segunda = self.receitas_no_banco()[1]
        self.client.post(f"/receitas/{segunda['id']}/excluir-proximos")
        self.assertEqual([r["data"] for r in self.receitas_no_banco()], ["2026-01-05"])

    # ------------------------------------------------- saldo atual e fatura (pago / não pago)
    def test_saldo_atual_so_desconta_o_que_foi_pago(self):
        hoje = date.today()
        self.receita(valor="1.000,00", data=hoje)
        self.adicionar("Mercado", "300,00", hoje)
        pagina = self.client.get("/").data.decode()
        self.assertEqual(self.saldo_atual(pagina), "R$ 1.000,00")        # ainda não pagou
        self.assertEqual(self.numeros_fatura(pagina), ("R$ 300,00", "R$ 0,00", "R$ 300,00"))
        self.marcar(1)
        pagina = self.client.get("/").data.decode()
        self.assertEqual(self.saldo_atual(pagina), "R$ 700,00")
        self.assertEqual(self.numeros_fatura(pagina), ("R$ 300,00", "R$ 300,00", "R$ 0,00"))
        self.assertIn("Quitada", pagina)

    def test_fluxo_do_exemplo_academia_seguro_amazon_pagos_e_apple_pendente(self):
        hoje = date.today()
        self.receita(descricao="Salário", valor="3.000,00", data=hoje)
        for nome, valor in (("Academia", "100,00"), ("Seguro", "350,00"),
                            ("Amazon", "80,00"), ("Apple", "40,00")):
            self.adicionar(nome, valor, hoje, "Contas")
        self.assertEqual(self.numeros_fatura(), ("R$ 570,00", "R$ 0,00", "R$ 570,00"))
        for gasto_id in (1, 2, 3):                                        # academia, seguro, amazon
            self.marcar(gasto_id)
        pagina = self.client.get("/").data.decode()
        self.assertEqual(self.numeros_fatura(pagina), ("R$ 570,00", "R$ 530,00", "R$ 40,00"))
        self.assertEqual(self.saldo_atual(pagina), "R$ 2.470,00")        # 3000 - 530
        self.assertIn("sobram <b class=\"positivo\">R$ 2.430,00</b>", pagina)  # depois do Apple
        self.assertNotIn("Quitada", pagina)
        # só o Apple fica na lista "falta pagar"; os pagos ficam recolhidos em "Já pagos"
        pendentes, pagos = pagina.split('<details class="pagos">')
        self.assertIn("Apple", pendentes.split('<ul class="lista">')[1])
        self.assertNotIn("Academia", pendentes.split('<ul class="lista">')[1])
        for nome in ("Academia", "Seguro", "Amazon"):
            self.assertIn(nome, pagos)
        self.assertIn("Já pagos (3)", pagina)
        self.marcar(4)                                                    # paga o Apple: quitou
        pagina = self.client.get("/").data.decode()
        self.assertEqual(self.numeros_fatura(pagina), ("R$ 570,00", "R$ 570,00", "R$ 0,00"))
        self.assertEqual(self.saldo_atual(pagina), "R$ 2.430,00")
        self.assertIn("Quitada", pagina)
        self.assertIn("Tudo pago neste mês", pagina)

    def test_saldo_negativo_e_aviso_quando_nao_cobre_a_fatura(self):
        hoje = date.today()
        self.receita(valor="100,00", data=hoje)
        self.adicionar("Aluguel", "400,00", hoje)
        pagina = self.client.get("/").data.decode()
        self.assertIn("O saldo não cobre o que falta: faltam "
                      "<b class=\"negativo\">R$ 300,00</b>", pagina)
        self.marcar(1)                                                    # pagou mesmo sem saldo
        pagina = self.client.get("/").data.decode()
        self.assertEqual(self.saldo_atual(pagina), "-R$ 300,00")
        self.assertRegex(pagina, r'class="saldo-valor negativo"')

    def test_receita_futura_nao_entra_no_saldo_atual_mas_aparece_como_a_receber(self):
        hoje = date.today()
        amanha = hoje + timedelta(days=1)
        if amanha.month != hoje.month:
            self.skipTest("hoje é o último dia do mês")
        self.receita(valor="500,00", data=amanha)
        pagina = self.client.get("/").data.decode()
        self.assertEqual(self.saldo_atual(pagina), "R$ 0,00")
        self.assertIn("Ainda a receber neste mês: <b>R$ 500,00</b>", pagina)

    def test_saldo_e_acumulado_entre_meses(self):
        self.receita(valor="1.000,00", data=date(2026, 1, 5))             # mês passado
        self.adicionar("Antigo pago", "200,00", date(2026, 1, 10), pago=True)
        self.adicionar("Antigo nao pago", "999,00", date(2026, 1, 11))    # não desconta
        self.assertEqual(self.saldo_atual(), "R$ 800,00")
        # a fatura é só do mês atual: gastos de janeiro não entram nela
        self.assertIn("Nenhum gasto neste mês ainda", self.client.get("/").data.decode())

    def test_gasto_futuro_marcado_como_pago_ja_desconta_do_saldo(self):
        self.receita(valor="1.000,00", data=date.today())
        self.adicionar("Adiantado", "250,00", date.today() + timedelta(days=60), pago=True)
        self.assertEqual(self.saldo_atual(), "R$ 750,00")

    def test_marcar_e_desmarcar_pago(self):
        self.adicionar("Conta", "10,00", date.today())
        self.assertEqual(self.gastos_no_banco()[0]["pago"], 0)
        self.marcar(1, pago=True)
        self.assertEqual(self.gastos_no_banco()[0]["pago"], 1)
        self.marcar(1, pago=False)                                        # checkbox desmarcado
        self.assertEqual(self.gastos_no_banco()[0]["pago"], 0)
        self.assertEqual(self.marcar(99).status_code, 404)

    def test_marcar_pago_volta_para_o_ponto_da_tela(self):
        self.adicionar("Conta", "10,00", date.today())
        resposta = self.marcar(1, next="/#fatura")
        self.assertEqual(resposta.headers["Location"], "/#fatura")
        resposta = self.marcar(1, next="https://exemplo.com")
        self.assertEqual(resposta.headers["Location"], "/")

    def test_ja_paguei_ao_criar_gasto(self):
        self.adicionar("Pago na hora", "10,00", date.today(), pago=True)
        self.adicionar("Fica pendente", "20,00", date.today())
        self.assertEqual([g["pago"] for g in self.gastos_no_banco()], [1, 0])

    def test_ja_paguei_em_recorrente_vale_so_para_o_mes_da_data(self):
        self.client.post("/gastos", data={
            "descricao": "Seguro", "valor": "350,00", "categoria": "Contas",
            "data": "2026-03-10", "recorrencia": "1", "pago": "1",
            "meses": ["2026-03", "2026-04", "2026-05"]})
        self.assertEqual([(g["data"], g["pago"]) for g in self.gastos_no_banco()],
                         [("2026-03-10", 1), ("2026-04-10", 0), ("2026-05-10", 0)])

    def test_copias_de_recorrencia_criadas_na_edicao_nascem_nao_pagas(self):
        self.adicionar("Seguro", "350,00", date(2026, 3, 10), "Contas", pago=True)
        self.editar_gasto(1, recorrencia="1", meses=["2026-03", "2026-04"])
        self.assertEqual([(g["data"], g["pago"]) for g in self.gastos_no_banco()],
                         [("2026-03-10", 1), ("2026-04-10", 0)])         # o original continua pago

    def test_editar_gasto_nao_mexe_no_pago(self):
        self.adicionar("Seguro", "350,00", date(2026, 3, 10), "Contas", pago=True)
        self.editar_gasto(1, descricao="Seguro novo")
        self.assertEqual(self.gastos_no_banco()[0]["pago"], 1)

    def test_formularios_mostram_ja_paguei_so_ao_criar(self):
        pagina = self.client.get("/").data.decode()
        self.assertIn("Já paguei", self.formulario(pagina, "/gastos"))
        self.adicionar("Algo", "5,00", date.today())
        edicao = self.client.get("/gastos/1/editar").data.decode()
        self.assertNotIn("Já paguei", self.formulario(edicao, "/gastos/1/editar"))

    def test_checkbox_pago_nas_listas_reflete_o_estado(self):
        self.adicionar("Pago", "10,00", date.today(), pago=True)
        self.adicionar("Pendente", "20,00", date.today())
        pagina = self.client.get("/lancamentos").data.decode()
        marcados = re.findall(r'class="caixa" name="pago" value="1" (checked)?', pagina)
        self.assertEqual(sorted(m or "nao" for m in marcados), ["checked", "nao"])
        self.assertIn('class="pago"', pagina)                             # item pago fica esmaecido
        self.assertEqual(self.client.get("/").data.decode().count('name="pago" value="1"'),
                         3)                                               # 2 na fatura + "Já paguei"

    def test_lancamentos_mostra_fatura_paga_e_o_que_falta(self):
        self.adicionar("A", "100,00", date(2026, 3, 5), pago=True)
        self.adicionar("B", "40,00", date(2026, 3, 6))
        pagina = self.client.get("/lancamentos?mes=2026-03").data.decode()
        self.assertRegex(pagina, r"Fatura do mês: <strong>R\$ 140,00</strong>")
        self.assertRegex(pagina, r'pago <strong class="positivo">R\$ 100,00</strong>')
        self.assertRegex(pagina, r'falta <strong class="negativo">R\$ 40,00</strong>')
        self.marcar(2)
        pagina = self.client.get("/lancamentos?mes=2026-03").data.decode()
        self.assertIn("Quitada", pagina)
        self.assertNotIn("falta <strong", pagina)

    def test_modulo_de_saldo_tem_botao_adicionar_saldo(self):
        pagina = self.client.get("/").data.decode()
        self.assertEqual(pagina.count("data-abrir-receita"), 2)           # topo (+) e módulo
        self.assertIn("+ Adicionar saldo", pagina)
        self.assertIn("Nenhum gasto neste mês ainda", pagina)

    def test_lancamentos_lista_receitas_do_mes(self):
        self.receita(descricao="Adiantamento", valor="800,00", data=date(2026, 3, 5))
        self.assertIn("Adiantamento".encode(), self.client.get("/lancamentos?mes=2026-03").data)
        self.assertNotIn("Adiantamento".encode(), self.client.get("/lancamentos?mes=2026-04").data)

    def test_botao_mais_esta_em_todas_as_telas(self):
        self.adicionar("Algo", "5,00", date.today())
        self.receita()
        for rota in ("/", "/lancamentos", "/gastos/1/editar", "/receitas/1/editar"):
            pagina = self.client.get(rota).data.decode()
            self.assertIn("data-abrir-receita", pagina, rota)
            self.assertIn('id="dialogo-receita"', pagina, rota)
            self.assertIn('name="quinzenal"', pagina, rota)

    # ---------------------------------------------------------------------- tema
    def test_seletor_de_tema_tem_tres_modos_e_tres_cores(self):
        pagina = self.client.get("/").data.decode()
        self.assertEqual(re.findall(r'data-modo="(\w+)"', pagina), ["light", "dark", "auto"])
        self.assertEqual(re.findall(r'data-cor="(\w+)"', pagina), ["verde", "azul", "roxo"])

    # ------------------------------------------------------------------ limpar tudo
    def test_limpar_tudo_apaga_gastos_e_receitas(self):
        self.adicionar("A", "10,00", date.today())
        self.adicionar("B", "20,00", date.today())
        self.receita(descricao="Salário")
        resposta = self.client.post("/limpar-tudo", follow_redirects=True)
        self.assertIn("2 gasto(s) e 1 receita(s) apagados".encode(), resposta.data)
        self.assertEqual(self.gastos_no_banco(), [])
        self.assertEqual(self.receitas_no_banco(), [])
        # depois de limpar, o app continua funcionando e aceita novos lançamentos
        self.adicionar("Novo", "5,00", date.today())
        self.assertEqual(len(self.gastos_no_banco()), 1)

    def test_botao_limpar_tudo_aparece_no_resumo_com_as_quantidades(self):
        self.adicionar("A", "10,00", date.today())
        self.receita()
        self.receita(descricao="Outra")
        pagina = self.client.get("/").data.decode()
        form = self.formulario(pagina, "/limpar-tudo")
        self.assertIn("Limpar tudo", form)
        self.assertIn("1 gasto(s) e 2 receita(s)", form)
        self.assertNotIn("disabled", form)

    def test_botao_limpar_tudo_fica_desativado_sem_lancamentos(self):
        form = self.formulario(self.client.get("/").data.decode(), "/limpar-tudo")
        self.assertIn("disabled", form)

    def test_limpar_tudo_nao_aparece_fora_do_resumo(self):
        self.assertNotIn("/limpar-tudo", self.client.get("/lancamentos").data.decode())

    # ------------------------------------------------- excluir "este e os seguintes"
    def botoes_excluir_rec(self, pagina):
        return re.findall(r"<button[^>]*data-excluir-rec[^>]*>", pagina)

    def test_excluir_de_item_recorrente_abre_a_janela_com_a_quantidade(self):
        self.recorrente(date(2026, 3, 10), ["2026-03", "2026-04", "2026-05"])
        pagina = self.client.get("/lancamentos?mes=2026-03").data.decode()
        [botao] = self.botoes_excluir_rec(pagina)
        self.assertIn('data-qtd="3"', botao)                      # ele + 2 seguintes
        self.assertIn('data-url-um="/gastos/1/excluir"', botao)
        self.assertIn('data-url-seguintes="/gastos/1/excluir-proximos"', botao)
        self.assertIn('id="dialogo-excluir"', pagina)
        # o botão antigo e separado "excluir próximos" não existe mais
        self.assertNotIn("excluir próximos", pagina)

    def test_ultimo_item_da_recorrencia_usa_excluir_simples(self):
        self.recorrente(date(2026, 3, 10), ["2026-03", "2026-04"])
        pagina = self.client.get("/lancamentos?mes=2026-04").data.decode()
        self.assertEqual(self.botoes_excluir_rec(pagina), [])     # nada depois dele
        self.assertIn('action="/gastos/2/excluir"', pagina)

    def test_item_avulso_usa_excluir_simples(self):
        self.adicionar("Avulso", "10,00", date(2026, 3, 10))
        pagina = self.client.get("/lancamentos?mes=2026-03").data.decode()
        self.assertEqual(self.botoes_excluir_rec(pagina), [])
        self.assertIn('action="/gastos/1/excluir"', pagina)

    def test_quantidade_conta_so_os_itens_a_partir_da_data_do_item(self):
        self.recorrente(date(2026, 3, 10), ["2026-03", "2026-04", "2026-05", "2026-06"])
        quantidades = {
            mes: re.search(r'data-qtd="(\d+)"', self.client.get(f"/lancamentos?mes={mes}").data.decode())
            for mes in ("2026-03", "2026-04", "2026-05", "2026-06")
        }
        self.assertEqual({m: (q.group(1) if q else None) for m, q in quantidades.items()},
                         {"2026-03": "4", "2026-04": "3", "2026-05": "2", "2026-06": None})

    def test_excluir_seguintes_a_partir_do_meio_mantem_os_anteriores(self):
        self.recorrente(date(2026, 3, 10), ["2026-03", "2026-04", "2026-05", "2026-06"])
        segundo = self.gastos_no_banco()[1]
        resposta = self.client.post(f"/gastos/{segundo['id']}/excluir-proximos",
                                    data={"next": "/lancamentos?mes=2026-04"}, follow_redirects=True)
        self.assertIn("3 gasto(s) da recorrência excluído(s)".encode(), resposta.data)  # abr, mai, jun
        self.assertEqual([g["data"] for g in self.gastos_no_banco()], ["2026-03-10"])

    def test_so_este_apaga_apenas_um(self):
        self.recorrente(date(2026, 3, 10), ["2026-03", "2026-04", "2026-05"])
        self.client.post("/gastos/2/excluir")
        self.assertEqual([g["data"] for g in self.gastos_no_banco()], ["2026-03-10", "2026-05-10"])

    def test_receita_recorrente_tambem_tem_a_janela(self):
        self.receita(descricao="Salário", data=date(2026, 3, 5), recorrencia="1",
                     meses=["2026-03", "2026-04", "2026-05"])
        pagina = self.client.get("/lancamentos?mes=2026-03").data.decode()
        [botao] = self.botoes_excluir_rec(pagina)
        self.assertIn('data-qtd="3"', botao)
        self.assertIn('data-url-seguintes="/receitas/1/excluir-proximos"', botao)

    def test_receita_quinzenal_recorrente_conta_os_dois_recebimentos_do_mes(self):
        # 2 recebimentos por mês, 2 meses: apagar "este e os seguintes" do 1º dia 5
        # leva junto o dia 20 do mesmo mês e os dois do mês seguinte (4 no total)
        self.receita(data=date(2026, 3, 5), quinzenal="1", dia2="20", recorrencia="1",
                     meses=["2026-03", "2026-04"])
        pagina = self.client.get("/lancamentos?mes=2026-03").data.decode()
        quantidades = sorted(re.findall(r'data-qtd="(\d+)"', pagina))
        self.assertEqual(quantidades, ["3", "4"])                 # dia 20 -> 3, dia 5 -> 4
        self.client.post("/receitas/1/excluir-proximos")
        self.assertEqual(self.receitas_no_banco(), [])

    # ------------------------------------------- proteção contra envio de outro site
    def test_post_vindo_de_outro_site_e_recusado(self):
        self.adicionar("A", "10,00", date.today())
        for cabecalhos in ({"Origin": "https://exemplo.com"},
                           {"Origin": "http://localhost:9999"},      # outra porta = outra origem
                           {"Origin": "null"},
                           {"Sec-Fetch-Site": "cross-site"}):
            resposta = self.client.post("/limpar-tudo", headers=cabecalhos)
            self.assertEqual(resposta.status_code, 403, cabecalhos)
        self.assertEqual(len(self.gastos_no_banco()), 1)           # nada foi apagado

    def test_post_do_proprio_site_e_aceito(self):
        self.adicionar("A", "10,00", date.today())
        resposta = self.client.post("/limpar-tudo", headers={
            "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(self.gastos_no_banco(), [])

    # ------------------------------------------------------------------ segurança
    def test_next_externo_e_ignorado(self):
        for destino in ("https://exemplo.com", "//exemplo.com", "/\\exemplo.com"):
            resposta = self.client.post("/receitas", data={
                "descricao": "X", "valor": "1", "data": "2026-03-05", "next": destino})
            self.assertEqual(resposta.headers["Location"], "/", destino)
        resposta = self.client.post("/receitas", data={
            "descricao": "X", "valor": "1", "data": "2026-03-05", "next": "/lancamentos?mes=2026-03"})
        self.assertEqual(resposta.headers["Location"], "/lancamentos?mes=2026-03")

    def test_migra_banco_da_v01(self):
        fd, caminho = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        con = sqlite3.connect(caminho)
        con.executescript(
            """
            CREATE TABLE gastos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                descricao TEXT NOT NULL,
                valor_centavos INTEGER NOT NULL CHECK (valor_centavos > 0),
                categoria TEXT NOT NULL,
                data TEXT NOT NULL,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO gastos (descricao, valor_centavos, categoria, data)
            VALUES ('Antigo', 1000, 'Outros', '2026-01-05');
            """
        )
        con.execute(
            "INSERT INTO gastos (descricao, valor_centavos, categoria, data) "
            "VALUES ('Deste mes', 2000, 'Outros', ?)", (date.today().isoformat(),))
        con.commit()
        con.close()
        try:
            rafinance.app.config["DATABASE"] = caminho
            rafinance.init_db()
            rafinance.init_db()  # rodar de novo não pode quebrar
            con = sqlite3.connect(caminho)
            colunas = [linha[1] for linha in con.execute("PRAGMA table_info(gastos)")]
            linhas = con.execute(
                "SELECT descricao, recorrencia_id, pago FROM gastos ORDER BY id").fetchall()
            con.close()
        finally:
            rafinance.app.config["DATABASE"] = self.db_path
            os.unlink(caminho)
        self.assertIn("recorrencia_id", colunas)
        self.assertIn("pago", colunas)
        # mês passado = histórico (pago); mês atual começa como não pago
        self.assertEqual(linhas, [("Antigo", None, 1), ("Deste mes", None, 0)])

    def test_migracao_do_pago_nao_repete_ao_reabrir_o_banco(self):
        self.adicionar("Deste mes", "20,00", date.today())
        rafinance.init_db()                       # reabrir não pode marcar nada como pago
        self.assertEqual(self.gastos_no_banco()[0]["pago"], 0)


if __name__ == "__main__":
    unittest.main()
