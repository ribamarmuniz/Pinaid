import logging
import json
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURAÇÃO ---
TOKEN = "8535108092:AAHwl_Ui-1lmj-2VqlzBg2pOpZPo4VQCIC0"  # <--- COLOCA O TEU TOKEN AQUI!!!
ARQUIVO_AGENDA = "agenda.json"
PASTA_IMAGENS = "imagens_pulseira"

# Garante que a pasta existe
if not os.path.exists(PASTA_IMAGENS):
    os.makedirs(PASTA_IMAGENS)

# Configuração de Log (para ver erros)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- FUNÇÕES AUXILIARES ---
def carregar_agenda():
    if os.path.exists(ARQUIVO_AGENDA):
        with open(ARQUIVO_AGENDA, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"medicamentos": []}

def salvar_agenda(dados):
    with open(ARQUIVO_AGENDA, 'w', encoding='utf-8') as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

# --- COMANDOS DO BOT ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Olá! Eu sou o Bot da Pulseira PIBIC.\n\n"
        "Comandos disponíveis:\n"
        "/novo <nome> <hora> <dose> - Adiciona um remédio (sem foto)\n"
        "Envie uma FOTO com a legenda 'nome, hora, dose' para cadastrar completo.\n\n"
        "Exemplo de foto: Tire foto da caixa e na legenda escreva: Losartana, 14:00, 50mg"
    )

async def adicionar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Exemplo: /novo Dipirona 20:00 1cp
    try:
        args = context.args
        if len(args) < 3:
            await update.message.reply_text("Erro. Use: /novo <nome> <hora> <dose>")
            return

        nome = args[0]
        hora = args[1]
        dose = " ".join(args[2:])

        agenda = carregar_agenda()
        novo_med = {
            "id": len(agenda['medicamentos']) + 1,
            "nome": nome,
            "dose": dose,
            "horario": hora,
            "img_arquivo": "" # Sem foto por enquanto
        }
        agenda['medicamentos'].append(novo_med)
        salvar_agenda(agenda)

        await update.message.reply_text(f"✅ Remédio {nome} adicionado para às {hora}!")
    except Exception as e:
        await update.message.reply_text(f"Erro ao salvar: {e}")

async def receber_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # O utilizador mandou uma foto. Vamos ver a legenda.
    legenda = update.message.caption
    
    if not legenda:
        await update.message.reply_text("⚠️ Por favor, envie a foto com uma legenda: Nome, Hora, Dose")
        return

    try:
        # Tenta separar a legenda por vírgula
        partes = [p.strip() for p in legenda.split(',')]
        if len(partes) < 3:
            await update.message.reply_text("Formato da legenda inválido. Use: Nome, Hora, Dose")
            return
            
        nome, hora, dose = partes[0], partes[1], partes[2]
        
        # Baixar a foto
        foto_arquivo = await update.message.photo[-1].get_file()
        nome_arquivo_imagem = f"{nome}_{hora.replace(':','')}.jpg"
        caminho_final = os.path.join(PASTA_IMAGENS, nome_arquivo_imagem)
        
        await foto_arquivo.download_to_drive(caminho_final)
        
        # Opcional: Aqui poderíamos chamar o script de redimensionar imagem (backend_simulado)
        # Para simplificar, vamos salvar direto e assumir que o backend trata ou a pulseira escala.
        
        # Atualizar JSON
        agenda = carregar_agenda()
        novo_med = {
            "id": len(agenda['medicamentos']) + 1,
            "nome": nome,
            "dose": dose,
            "horario": hora,
            "img_arquivo": nome_arquivo_imagem
        }
        # Remove anteriores se quiser limpar a lista, ou adiciona (append)
        # agenda['medicamentos'] = [novo_med] # Modo teste: substitui tudo
        agenda['medicamentos'].append(novo_med) # Modo real: adiciona
        
        salvar_agenda(agenda)
        
        await update.message.reply_text(f"📸 Foto recebida! {nome} agendado para {hora}.")
        
    except Exception as e:
        await update.message.reply_text(f"Erro ao processar foto: {e}")

if __name__ == '__main__':
    print("--- INICIANDO CHATBOT TELEGRAM ---")
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("novo", adicionar_texto))
    app.add_handler(MessageHandler(filters.PHOTO, receber_foto))
    
    app.run_polling()