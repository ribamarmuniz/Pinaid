import time
import requests
import datetime

# URL onde o Rasa esta ouvindo
RASA_URL = "http://localhost:5005/conversations/usuario_teste/trigger_intent"

def verificar_alarme():
    print("[DESPERTADOR] Sistema de monitoramento iniciado...")
    
    contador = 0
    while True:
        # A cada 10 segundos envia o sinal (para teste)
        if contador >= 10:
            print("[SISTEMA] ENVIANDO COMANDO: Disparar Lembrete...")
            
            payload = {
                "name": "gatilho_externo_lembrete",
                "entities": {}
            }
            
            try:
                resposta = requests.post(RASA_URL, json=payload)
                
                if resposta.status_code == 200:
                    print(f"[SUCESSO] O Robo recebeu o comando. (Status 200)")
                else:
                    print(f"[ALERTA] O Robo respondeu com codigo {resposta.status_code}")
                
                contador = 0 
                
            except Exception as e:
                # Se der erro, e porque o Rasa ainda esta carregando.
                print(f"[FALHA DE CONEXAO] O Servidor Rasa ainda nao esta pronto. Aguardando...")

        time.sleep(1)
        contador += 1
        # Imprime pontinhos para mostrar que o script nao travou
        print(".", end="", flush=True)

if __name__ == "__main__":
    verificar_alarme()