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

    def adicionar(self, descricao, valor, data, categoria="Outros"):
        return self.client.post(
            "/gastos",
            data={
                "descricao": descricao,
                "valor": valor,
                "categoria": categoria,
                "data": data.isoformat(),
            },
            follow_redirects=True,
        )

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

    def test_a_vencer_fica_fora_dos_totais(self):
        hoje = date.today()
        amanha = hoje + timedelta(days=1)
        self.adicionar("Gasto de hoje", "10,00", hoje)
        self.adicionar("Boleto de amanha", "500,00", amanha)
        pagina = self.client.get("/").data.decode()
        cartoes = re.findall(r"<strong>(R\$ [\d.,]+)</strong>", pagina)
        self.assertEqual(cartoes[:3], ["R$ 10,00"] * 3)  # hoje, semana, mês
        if amanha.month == hoje.month:
            self.assertIn("A vencer neste mês", pagina)
            self.assertIn("Boleto de amanha", pagina)
        else:
            self.assertNotIn("Boleto de amanha", pagina)

    def test_meses_a_partir_vira_o_ano(self):
        opcoes = rafinance.meses_a_partir(date(2026, 11, 2), 4)
        self.assertEqual(
            [o["valor"] for o in opcoes], ["2026-11", "2026-12", "2027-01", "2027-02"]
        )
        self.assertEqual(opcoes[2]["rotulo"], "jan/27")

    def test_formulario_tem_recorrencia_so_ao_criar(self):
        pagina = self.client.get("/").data.decode()
        self.assertIn("Recorrência", pagina)
        self.assertEqual(pagina.count('name="meses"'), 12)
        self.adicionar("Algo", "5,00", date.today())
        self.assertNotIn("Recorrência", self.client.get("/gastos/1/editar").data.decode())

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
        con.commit()
        con.close()
        try:
            rafinance.app.config["DATABASE"] = caminho
            rafinance.init_db()
            rafinance.init_db()  # rodar de novo não pode quebrar
            con = sqlite3.connect(caminho)
            colunas = [linha[1] for linha in con.execute("PRAGMA table_info(gastos)")]
            linhas = con.execute("SELECT descricao, recorrencia_id FROM gastos").fetchall()
            con.close()
        finally:
            rafinance.app.config["DATABASE"] = self.db_path
            os.unlink(caminho)
        self.assertIn("recorrencia_id", colunas)
        self.assertEqual(linhas, [("Antigo", None)])


if __name__ == "__main__":
    unittest.main()
