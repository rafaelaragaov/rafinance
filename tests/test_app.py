import os
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


if __name__ == "__main__":
    unittest.main()
