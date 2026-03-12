from flask import Flask, jsonify, request, render_template
import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

ESTOQUE_MINIMO = 5

# ── Campos obrigatórios e suas validações ──────────────────────────────────────

CAMPOS_PRODUTO = ["codigo", "nome", "categoria", "quantidade", "preco", "descricao", "fornecedor"]

VALIDACOES = {
    "preco":      lambda v: float(v) >= 0,
    "quantidade": lambda v: int(v) >= 0,
}

MENSAGENS_ERRO = {
    "preco":      "O preço não pode ser negativo.",
    "quantidade": "A quantidade não pode ser negativa.",
}


# ── Classe de configuração do banco ───────────────────────────────────────────

class DatabaseConfig:
    def __init__(self):
        self.host     = os.environ.get("DB_HOST")
        self.port     = int(os.environ.get("DB_PORT", 3306))
        self.user     = os.environ.get("DB_USER")
        self.password = os.environ.get("DB_PASS")
        self.database = os.environ.get("DB_NAME")

    def to_dict(self):
        return {
            "host":     self.host,
            "port":     self.port,
            "user":     self.user,
            "password": self.password,
            "database": self.database,
        }


# ── Classe de acesso ao banco ─────────────────────────────────────────────────

class Database:
    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS produtos (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            codigo      VARCHAR(50)    NOT NULL UNIQUE,
            nome        VARCHAR(100)   NOT NULL,
            categoria   VARCHAR(50)    NOT NULL,
            quantidade  INT            NOT NULL DEFAULT 0,
            preco       DECIMAL(10,2)  NOT NULL,
            descricao   VARCHAR(255),
            fornecedor  VARCHAR(100)
        )
    """

    def __init__(self, config: DatabaseConfig):
        self.config = config

    def get_conn(self):
        conn = mysql.connector.connect(**self.config.to_dict())
        self._criar_tabela(conn)
        return conn

    def _criar_tabela(self, conn):
        cur = conn.cursor()
        cur.execute(self.CREATE_TABLE_SQL)
        conn.commit()
        cur.close()


# ── Classe de modelo do produto ───────────────────────────────────────────────

class Produto:
    COLUNAS = ["id", "codigo", "nome", "categoria", "quantidade", "preco", "descricao", "fornecedor"]

    def __init__(self, row: tuple):
        # Mapeia as colunas da tupla usando loop
        for campo, valor in zip(self.COLUNAS, row):
            setattr(self, campo, valor)
        self.preco = float(self.preco)
        self.baixo = self.quantidade <= ESTOQUE_MINIMO

    def to_dict(self) -> dict:
        resultado = {campo: getattr(self, campo) for campo in self.COLUNAS}
        resultado["preco"] = self.preco
        resultado["baixo"] = self.baixo
        return resultado

    @staticmethod
    def validar(dados: dict) -> list[str]:
        """Retorna lista de erros de validação."""
        erros = []
        for campo, regra in VALIDACOES.items():
            if campo in dados:
                try:
                    if not regra(dados[campo]):
                        erros.append(MENSAGENS_ERRO[campo])
                except (ValueError, TypeError):
                    erros.append(f"Valor inválido para '{campo}'.")
        return erros


# ── Classe de serviço de estoque ──────────────────────────────────────────────

class EstoqueService:
    ACOES = {
        "adicionar": lambda atual, qtd: atual + qtd,
        "remover":   lambda atual, qtd: atual - qtd,
        "definir":   lambda atual, qtd: qtd,
    }

    def calcular_nova_quantidade(self, acao: str, atual: int, qtd: int) -> tuple[int | None, str | None]:
        """Retorna (nova_quantidade, erro). Se erro != None, houve falha."""
        if acao not in self.ACOES:
            return None, f"Ação inválida. Use: {', '.join(self.ACOES.keys())}."

        if acao == "remover" and qtd > atual:
            return None, f"Estoque insuficiente. Disponível: {atual}."

        if acao == "definir" and qtd < 0:
            return None, "Quantidade não pode ser negativa."

        nova = self.ACOES[acao](atual, qtd)
        return nova, None


# ── Inicialização global ───────────────────────────────────────────────────────

db_config = DatabaseConfig()
db        = Database(db_config)
estoque   = EstoqueService()

print("DB:", db_config.database)


# ── Página principal ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/produtos", methods=["GET"])
def listar():
    try:
        conn = db.get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT * FROM produtos ORDER BY nome")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # Usa loop + classe para converter cada linha
        produtos = [Produto(row).to_dict() for row in rows]
        return jsonify(produtos)
    except Error as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/produtos", methods=["POST"])
def cadastrar():
    d = request.json

    # Valida campos obrigatórios em loop
    faltando = [c for c in CAMPOS_PRODUTO if c not in d]
    if faltando:
        return jsonify({"erro": f"Campos obrigatórios ausentes: {', '.join(faltando)}"}), 400

    # Valida preço e quantidade negativos
    erros = Produto.validar(d)
    if erros:
        return jsonify({"erro": " | ".join(erros)}), 400

    sql = """INSERT INTO produtos (codigo, nome, categoria, quantidade, preco, descricao, fornecedor)
             VALUES (%s,%s,%s,%s,%s,%s,%s)"""
    valores = tuple(d[c] for c in CAMPOS_PRODUTO[1:])  # exclui 'id' (auto)

    try:
        conn = db.get_conn()
        cur  = conn.cursor()
        cur.execute(sql, valores)
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True, "msg": f"Produto '{d['nome']}' cadastrado!"})
    except Error as e:
        if e.errno == 1062:
            return jsonify({"erro": f"Código '{d['codigo']}' já existe."}), 400
        return jsonify({"erro": str(e)}), 500


@app.route("/api/produtos/<codigo>", methods=["GET"])
def buscar(codigo):
    try:
        conn = db.get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT * FROM produtos WHERE codigo=%s", (codigo,))
        row  = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"erro": "Produto não encontrado."}), 404
        return jsonify(Produto(row).to_dict())
    except Error as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/produtos/<codigo>/estoque", methods=["PATCH"])
def atualizar_estoque(codigo):
    d    = request.json
    acao = d.get("acao")
    qtd  = int(d.get("quantidade", 0))

    try:
        conn = db.get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT quantidade, nome FROM produtos WHERE codigo=%s", (codigo,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify({"erro": "Produto não encontrado."}), 404

        atual, nome = row[0], row[1]
        nova, erro  = estoque.calcular_nova_quantidade(acao, atual, qtd)

        if erro:
            cur.close(); conn.close()
            return jsonify({"erro": erro}), 400

        cur.execute("UPDATE produtos SET quantidade=%s WHERE codigo=%s", (nova, codigo))
        conn.commit()
        cur.close()
        conn.close()

        alerta = nova <= ESTOQUE_MINIMO
        return jsonify({
            "ok":       True,
            "quantidade": nova,
            "alerta":   alerta,
            "nome":     nome,
            "msg":      f"Estoque atualizado para {nova} unidades.",
        })
    except Error as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/produtos/<codigo>", methods=["DELETE"])
def deletar(codigo):
    try:
        conn = db.get_conn()
        cur  = conn.cursor()
        cur.execute("DELETE FROM produtos WHERE codigo=%s", (codigo,))
        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()
        if affected == 0:
            return jsonify({"erro": "Produto não encontrado."}), 404
        return jsonify({"ok": True, "msg": "Produto removido."})
    except Error as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/alertas", methods=["GET"])
def alertas():
    try:
        conn = db.get_conn()
        cur  = conn.cursor()
        cur.execute(
            "SELECT * FROM produtos WHERE quantidade <= %s ORDER BY quantidade",
            (ESTOQUE_MINIMO,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # Loop com classe para mapear os resultados
        return jsonify([Produto(row).to_dict() for row in rows])
    except Error as e:
        return jsonify({"erro": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8080)