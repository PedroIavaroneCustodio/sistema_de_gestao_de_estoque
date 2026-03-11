from flask import Flask, jsonify, request, render_template
import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

CONFIG = {
    "host":     os.environ.get("DB_HOST"),
    "port":     int(os.environ.get("DB_PORT", 3306)),
    "user":     os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASS"),
    "database": os.environ.get("DB_NAME"),
}

print(os.environ.get("DB_NAME"))

ESTOQUE_MINIMO = 5


def get_conn():
    conn = mysql.connector.connect(**CONFIG)
    criar_tabela(conn)
    return conn


def criar_tabela(conn):
    sql = """
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
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()


def row_to_dict(row):
    return {
        "id":         row[0],
        "codigo":     row[1],
        "nome":       row[2],
        "categoria":  row[3],
        "quantidade": row[4],
        "preco":      float(row[5]),
        "descricao":  row[6],
        "fornecedor": row[7],
        "baixo":      row[4] <= ESTOQUE_MINIMO,
    }


# ── Página principal ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/produtos", methods=["GET"])
def listar():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM produtos ORDER BY nome")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([row_to_dict(r) for r in rows])
    except Error as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/produtos", methods=["POST"])
def cadastrar():
    d = request.json
    sql = """INSERT INTO produtos (codigo, nome, categoria, quantidade, preco, descricao, fornecedor)
             VALUES (%s,%s,%s,%s,%s,%s,%s)"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(sql, (d["codigo"], d["nome"], d["categoria"],
                          d["quantidade"], d["preco"], d["descricao"], d["fornecedor"]))
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
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM produtos WHERE codigo=%s", (codigo,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"erro": "Produto não encontrado."}), 404
        return jsonify(row_to_dict(row))
    except Error as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/produtos/<codigo>/estoque", methods=["PATCH"])
def atualizar_estoque(codigo):
    d = request.json
    acao = d.get("acao")        # "adicionar" | "remover" | "definir"
    qtd  = int(d.get("quantidade", 0))

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT quantidade, nome FROM produtos WHERE codigo=%s", (codigo,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "Produto não encontrado."}), 404

        atual, nome = row[0], row[1]

        if acao == "adicionar":
            nova = atual + qtd
        elif acao == "remover":
            if qtd > atual:
                return jsonify({"erro": f"Estoque insuficiente. Disponível: {atual}"}), 400
            nova = atual - qtd
        elif acao == "definir":
            if qtd < 0:
                return jsonify({"erro": "Quantidade não pode ser negativa."}), 400
            nova = qtd
        else:
            return jsonify({"erro": "Ação inválida."}), 400

        cur.execute("UPDATE produtos SET quantidade=%s WHERE codigo=%s", (nova, codigo))
        conn.commit()
        cur.close()
        conn.close()
        alerta = nova <= ESTOQUE_MINIMO
        return jsonify({"ok": True, "quantidade": nova, "alerta": alerta,
                        "nome": nome, "msg": f"Estoque atualizado para {nova} unidades."})
    except Error as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/produtos/<codigo>", methods=["DELETE"])
def deletar(codigo):
    try:
        conn = get_conn()
        cur = conn.cursor()
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
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM produtos WHERE quantidade <= %s ORDER BY quantidade", (ESTOQUE_MINIMO,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([row_to_dict(r) for r in rows])
    except Error as e:
        return jsonify({"erro": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8080)