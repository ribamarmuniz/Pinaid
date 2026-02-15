from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
import datetime

class ActionVerificarHorario(Action):

    def name(self) -> Text:
        return "action_verificar_horario"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        agora = datetime.datetime.now()
        hora = agora.hour
        minuto = agora.minute
        
        vibrar_pulseira = False

        if hora >= 18:
            mensagem = f"Agora sao {hora}:{minuto}. Dona Maria, hora do remedio de pressao (Noite)."
            vibrar_pulseira = True
        elif hora < 12:
            mensagem = f"Bom dia. Sao {hora}:{minuto}. Hora do remedio de diabetes (Manha)."
            vibrar_pulseira = True
        else:
            mensagem = f"Sao {hora}:{minuto}. Nenhum remedio agora. Proximo as 18h."
            vibrar_pulseira = False

        # --- SIMULACAO DO HARDWARE (PULSEIRA) ---
        if vibrar_pulseira:
            print("\n" + "="*40)
            print("[SISTEMA IOT] Conectando a Pulseira (ID: ESP32_01)...")
            print("[COMANDO] ENVIAR VIBRACAO: PADRAO 'ALERTA'")
            print("[STATUS] Pulseira Vibrou com Sucesso.")
            print("="*40 + "\n")
            
            mensagem += " (Sinal de vibracao enviado para a pulseira)"

        dispatcher.utter_message(text=mensagem)

        return []