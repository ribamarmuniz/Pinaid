from flask import Flask, jsonify, send_from_directory, request
import json
import os

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
PASTA_IMAGENS = "imagens_pulseira"
ARQUIVO_AGENDA = "agenda.json"

# Garante que as pastas existem
if not os.path.exists(PASTA_IMAGENS):
    os.makedirs(PASTA_IMAGENS)

# Dados iniciais (Simulando o Banco de Dados)
# Na versão final, isso virá do Rasa/Telegram
def carregar_agenda_db():
    if os.path.exists(ARQUIVO_AGENDA):
        with open(ARQUIVO_AGENDA, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"erro": "Agenda não encontrada"}

# --- ROTAS DA API (Endpoints) ---

@app.route('/')
def home():
    return "<h1>Servidor PIBIC Online</h1><p>O Cérebro está funcionando.</p>"

# 1. Rota para a Pulseira baixar a agenda (GET)
@app.route('/api/agenda', methods=['GET'])
def get_agenda():
    print(f"[SERVIDOR] Pulseira solicitou atualização de agenda...")
    dados = carregar_agenda_db()
    return jsonify(dados)

# 2. Rota para a Pulseira baixar as imagens (GET)
@app.route('/api/imagens/<path:filename>')
def get_imagem(filename):
    print(f"[SERVIDOR] Pulseira baixando imagem: {filename}")
    return send_from_directory(PASTA_IMAGENS, filename)

# 3. Rota para a Pulseira enviar confirmação (POST)
@app.route('/api/confirmar', methods=['POST'])
def receber_confirmacao():
    dados = request.json
    print(f"✅ [LOG RECEBIDO] Usuário confirmou: {dados}")
    # Aqui salvaríamos no banco de dados real
    return jsonify({"status": "sucesso", "mensagem": "Log registrado no servidor"})

if __name__ == '__main__':
    print("--- INICIANDO SERVIDOR CENTRAL (CÉREBRO) ---")
    print("Aguardando conexões da pulseira em http://127.0.0.1:5000")
    # host='0.0.0.0' permite que dispositivos reais na mesma rede conectem
    app.run(host='0.0.0.0', port=5000, debug=True)